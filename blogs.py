import logging
from datetime import timedelta
import os
import sys

from google.appengine.api.labs import taskqueue
from google.appengine.api import urlfetch
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp import util


path = os.path.join(os.path.dirname(__file__), 'lib')
sys.path.insert(0, path)

import feedparser
from ningapi import NingError
import oauth2 as oauth

import config
from auth import Credential, require_credentials
import timeutils


class ContentFeed(db.Model):
    url = db.LinkProperty(required=True)
    last_update = db.DateTimeProperty(auto_now_add=True)
    owner = db.UserProperty(required=True)


class ContentEntry(db.Model):
    pub_date = db.DateTimeProperty(auto_now_add=True)
    owner = db.UserProperty(required=True)
    title = db.StringProperty(required=True)
    description = db.TextProperty(required=True)
    ning_id = db.StringProperty(required=False)
    retry_count = db.IntegerProperty(required=True, default=0)


class FeedConfig(webapp.RequestHandler):

    @require_credentials
    def get(self):
        """Display a template for adding a new feed"""

        template_values = {
            "success": self.request.get("success", False)}
        path = os.path.join(os.path.dirname(__file__),
            'templates/blog-new.html')
        self.response.out.write(template.render(path, template_values))

    @require_credentials
    def post(self):
        """Save the feed to a new Feed object"""

        feed_url = self.request.get("url", None)

        try:
            feed = ContentFeed(url=feed_url, owner=users.get_current_user())
        except db.BadValueError, e:
            template_values = {
                "failure": str(e)}
            path = os.path.join(os.path.dirname(__file__),
                'templates/blog-new.html')
            self.response.out.write(template.render(path, template_values))
            return

        feed.put()
        logging.info("Added new feed: \"%s\"", feed.url)
        self.redirect("/blogs/admin/new?success=1")


class FeedBrowser(webapp.RequestHandler):

    @require_credentials
    def get(self):
        """Display the list of feeds"""

        url = self.request.get("url")
        if url:
            # display details of a feed
            pass

        else:
            query = ContentFeed.all()

            # Admins can see all feeds
            if not users.is_current_user_admin():
                query.filter("owner =", users.get_current_user())

            feeds = []
            for feed in query:
                feeds.append({
                    "url": feed.url,
                    "last_updated": feed.last_update.ctime(),
                    "owner_email": feed.owner.email()})

            template_values = {"feeds": feeds}
            path = os.path.join(os.path.dirname(__file__),
                'templates/blog-browse.html')
            self.response.out.write(template.render(path, template_values))


class FeedProducer(webapp.RequestHandler):

    def get(self):
        """
        Query the DB and queue any feeds that haven't been processed since
        update_interval
        """

        update_interval = timedelta(hours=1)

        current_datetime = timeutils.now_utc()

        query = ContentFeed.all()
        query.filter("last_update <", current_datetime - update_interval)

        if query.count() == 0:
            logging.debug("No entries to queue")
        else:
            for feed in query:
                # get the member's OAuth token and secret

                last_update = timeutils.add_utc_tzinfo(feed.last_update)
                feed_consumer_params = {
                    "feed_key": feed.key(),
                    "owner_id": feed.owner.user_id()}

                try:
                    taskqueue.add(url="/blogs/feed/consumer",
                        params=feed_consumer_params)
                    logging.debug("Queued feed: \"%s\" %s" %
                        (feed.url, last_update.ctime()))
                except taskqueue.Error:
                    logging.error("Unable to queue feed: \"%s\"",
                        feed.url)
                    return


class FeedConsumer(webapp.RequestHandler):

    def post(self):
        """
        Use feedparser to save any blog posts from the given URL since
        the given timestamp
        """

        feed_key = self.request.get("feed_key", None)
        if not feed_key:
            logging.error("No feed URL provided")
            return

        feed = ContentFeed.get(feed_key)

        if not feed:
            logging.error("Couldn't find feed in the DB \"%s\"" % feed_key)
            return

        logging.debug("Dequeued feed: \"%s\"" % (feed.url))

        last_update = timeutils.add_utc_tzinfo(feed.last_update)
        logging.debug("Last processed feed on: %s" % last_update.ctime())

        try:
            result = urlfetch.fetch(feed.url)
        except urlfetch.Error, e:
            logging.warn("Exception when fetching feed: \"%s\" %s" %
                (feed.url, e))
            return

        if result.status_code != 200:
            logging.warn("Unable to fetch feed: (%s) \"%s\"" %
             (result.status_code, feed.url))
            return

        current_datetime = timeutils.now_utc()

        d = feedparser.parse(result.content)
        if not d.feed:
            logging.error("Unable to parse feed: \"%s\"" % feed.url)
            return

        for entry in d.entries:
            if not "updated_parsed" in entry:
                logging.warning("Entry doesn't have an updated date, skipping")
                continue
            if not "title" in entry:
                logging.warning("Entry is missing a title, skipping")
                continue
            if not "description" in entry:
                logging.warning("Entry is missing a description, skipping")
                continue
            if not "link" in entry:
                logging.warning("Entry is missing a link, skipping")
                continue

            entry_datetime = timeutils.struct_to_datetime(entry.updated_parsed)

            if entry_datetime < last_update:
                logging.debug("Stopping processing with: \"%s\" @ %s" %
                    (entry.title, entry_datetime.ctime()))
                break

            if "content" in entry and len(entry.content) > 0:
                entry_content = entry.content[0].value
            else:
                entry_content = ""

            if "description" in entry:
                entry_description = entry.description
            else:
                entry_description = ""

            # Choose a body that has the most content
            if len(entry_content) > len(entry_description):
                body = entry_content
            else:
                body = entry_description

            body = '%s\n\n<a href="%s">Original post</a>' % (body, entry.link)

            # Save the entry to the DB
            db_entry = ContentEntry(title=entry.title, description=body,
                owner=feed.owner)
            db_entry.put()

            logging.info("Saved entry: \"%s\" @ %s" % (entry.title,
                entry_datetime.ctime()))

        feed.last_update = current_datetime
        feed.put()


class EntryProducer(webapp.RequestHandler):

    def get(self):
        """
        Query the DB and queue any entries that haven't been uploaded yet
        """

        query = ContentEntry.all()
        query.filter("pub_date <", timeutils.now_utc())
        query.filter("ning_id =", None)

        if query.count() == 0:
            logging.debug("No entries to queue")
        else:
            for entry in query:

                # Backoff method for trying to upload
                if entry.retry_count > 100:
                    logging.info("Too many retries, deleting \"%s\"" %
                        entry.title)
                    entry.delete()
                    continue
                next_try = timeutils.add_utc_tzinfo(entry.pub_date +
                    timedelta(minutes=entry.retry_count**2))
                if next_try > timeutils.now_utc():
                    logging.debug("Too soon to retry, will try again at %s" %
                        next_try.ctime())
                    continue

                entry_consumer_params = {
                    "entry_key": entry.key()}
                try:
                    taskqueue.add(url="/blogs/entry/consumer",
                        params=entry_consumer_params)
                    logging.debug("Queued entry: \"%s\" %s" %
                        (entry.title, entry.pub_date.ctime()))
                except taskqueue.Error:
                    logging.error("Unable to queue feed: \"%s\"",
                        entry_consumer_params["url"])
                    return


class EntryConsumer(webapp.RequestHandler):

    def post(self):
        """Publish the given blog post to the configured Ning Network"""

        entry_key = self.request.get("entry_key", None)
        if not entry_key:
            logging.warn("No entry_key provided")
            return

        entry = ContentEntry.get(entry_key)
        if not entry:
            logging.warn("Entry not found in the DB: %s" % entry_key)
            return

        entry.retry_count += 1
        entry.put()

        logging.debug("Dequeued entry: \"%s\" %s" % (entry.title,
            entry.pub_date.ctime()))

        credentials = Credential.all().filter("owner =", entry.owner).get()
        if not credentials:
            logging.error("No credentials found for %s" % entry.owner)
            return


        blog_parts = {
            "title": entry.title.encode("utf-8"),
            "description": entry.description.encode("utf-8"),
            # "publishTime": unicode(publish_time.isoformat()).encode("utf-8")
        }

        token = oauth.Token(key=credentials.token_key,
            secret=credentials.token_secret)
        ning_client = config.new_client(token)

        try:
            response = ning_client.post("BlogPost", blog_parts)
        except NingError, e:
            logging.error("Unable to upload: %s" % str(e))
            return

        logging.info("Uploaded blog post: \"%s\" %s" % (entry.title,
            response['id']))

        entry.delete()


def main():
    application = webapp.WSGIApplication([
            ('/blogs/feed/producer', FeedProducer),
            ('/blogs/feed/consumer', FeedConsumer),
            ('/blogs/entry/producer', EntryProducer),
            ('/blogs/entry/consumer', EntryConsumer),
            ('/blogs/admin/new', FeedConfig),
            ('/blogs/admin/view', FeedBrowser),
        ],
        debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
