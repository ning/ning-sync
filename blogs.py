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
from iso8601 import iso8601
from ningapi import NingError
import oauth2 as oauth

import config
from auth import Credential, require_credentials
import timeutils


class ContentFeed(db.Model):
    url = db.LinkProperty(required=True)
    last_update = db.DateTimeProperty(auto_now_add=True)
    owner = db.UserProperty(required=True)


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
                "failure": str(e)
            }
            path = os.path.join(os.path.dirname(__file__),
                'templates/blog-new.html')
            self.response.out.write(template.render(path, template_values))
            return
        
        feed.put()
        logging.info("Added new feed: \"%s\"", feed_url)
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

        for feed in query:
            # get the member's OAuth token and secret

            query = Credential.all().filter("owner =", feed.owner)
            credentials = query.fetch(limit=10)
            if len(credentials) != 1:
                logging.error("Feed owner doesn't have credentials, skipping")
                continue
            cred = credentials[0]

            last_update = timeutils.add_utc_tzinfo(feed.last_update)
            feed_consumer_params = {
                "url": feed.url,
                "timestamp": last_update.isoformat(),
                "key": cred.token_key,
                "secret": cred.token_secret}

            try:
                taskqueue.add(url="/blogs/feed/consumer",
                    params=feed_consumer_params)
                logging.info("Queued feed: \"%s\" %s" %
                    (feed_consumer_params["url"], last_update.ctime()))
            except taskqueue.Error:
                logging.info("Unable to queue feed: \"%s\"",
                    feed_consumer_params["url"])
                return

            feed.last_update = current_datetime
            feed.put()


class FeedConsumer(webapp.RequestHandler):

    def post(self):
        """
        Use feedparser to queue any blog posts from the given URL since
        the given timestamp
        """

        feed_url = self.request.get("url", None)
        if not feed_url:
            logging.error("No feed URL provided")
            return
        last_timestamp = self.request.get("timestamp", None)
        if not last_timestamp:
            logging.error("No timestamp provided")
            return
        key = self.request.get("key", None)
        if not key:
            logging.error("Feed missing OAuth key")
            return
        secret = self.request.get("secret", None)
        if not secret:
            logging.error("Feed missing OAuth secret")
            return

        last_update = iso8601.parse_date(last_timestamp)
        logging.info("Last processed feed on: %s" % last_update.ctime())

        try:
            result = urlfetch.fetch(feed_url)
        except urlfetch.Error, e:
            logging.error("Exception when fetching feed: \"%s\" %s" %
                (feed_url, e))
            return

        if result.status_code != 200:
            logging.error("Unable to fetch feed: (%s) \"%s\"" %
             (result.status_code, feed_url))
            return

        d = feedparser.parse(result.content)
        if not d.feed:
            logging.error("Unable to parse feed: \"%s\"" % feed_url)
            return

        if d.feed.has_key("title"):
            logging.info("Processing Feed: \"%s\"" % d.feed.title)

        for entry in d.entries:
            if not entry.has_key("updated_parsed"):
                logging.warning("Entry doesn't have an updated date, skipping")
                continue
            if not entry.has_key("title"):
                logging.warning("Entry is missing a title, skipping")
                continue
            if not entry.has_key("description"):
                logging.warning("Entry is missing a description, skipping")
                continue
            if not entry.has_key("link"):
                logging.warning("Entry is missing a link, skipping")
                continue

            entry_datetime = timeutils.struct_to_datetime(entry.updated_parsed)

            if entry_datetime < last_update:
                break

            blog_consumer_params = {
                "title": entry.title,
                "description": '%s\n\n<a href="%s">Continue reading</a>' %
                    (entry.description, entry.link),
                "publishTime": entry_datetime.isoformat(),
                "key": key,
                "secret": secret,
            }
            logging.info("Queued: \"%s\" @ %s" % (entry.title,
                entry_datetime.ctime()))
            taskqueue.add(url="/blogs/photo/consumer",
                params=blog_consumer_params)


class EntryConsumer(webapp.RequestHandler):

    def post(self):
        """Publish the given blog post to the configured Ning Network"""

        timestamp = self.request.get("publishTime", None)
        if not timestamp:
            logging.error("No timestamp provided")
            return

        publish_time = iso8601.parse_date(timestamp)

        title = self.request.get("title", None)
        description = self.request.get("description", None)
        key = self.request.get("key", None)
        secret = self.request.get("secret", None)

        blog_parts = {
            "title": title.encode("utf-8"),
            "description": description.encode("utf-8"),
            "publishTime": unicode(publish_time.isoformat()).encode("utf-8")}

        token = oauth.Token(key=key, secret=secret)
        ning_client = config.new_client(token)

        try:
            ning_client.post("BlogPost", blog_parts)
        except NingError, e:
            logging.error("Unable to upload: %s" % str(e))
            return

        logging.info("Dequeued: \"%s\" %s" % (blog_parts["title"],
            publish_time.ctime()))


def main():
    application = webapp.WSGIApplication([
            ('/blogs/feed/producer', FeedProducer),
            ('/blogs/feed/consumer', FeedConsumer),
            ('/blogs/photo/consumer', EntryConsumer),
            ('/blogs/admin/new', FeedConfig),
            ('/blogs/admin/view', FeedBrowser),
        ],
        debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
