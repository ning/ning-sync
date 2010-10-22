import os
import sys
import logging

from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp import util

path = os.path.join(os.path.dirname(__file__), 'lib')
sys.path.insert(0, path)

import config
from ningapi import NingError


class Credential(db.Model):
    owner = db.UserProperty(required=True)
    token_key = db.StringProperty(required=True)
    token_secret = db.StringProperty(required=True)
    email = db.EmailProperty(required=True)


class AuthConfig(webapp.RequestHandler):

    def get(self):
        """Display a template for adding credentials"""
        template_values = {
            "success": self.request.get("success", False)}

        current_user = users.get_current_user()

        query = Credential.all().filter("owner =", current_user)
        if query.count() > 0:
            logging.warn("%s already authorized" % current_user.email())
            path = os.path.join(os.path.dirname(__file__),
                'templates/auth-error.html')
            template_values = {"error_message":
                "You have already authorized this application. " +
                "<a href='/auth/admin/view'>View existing?</a>"}
            self.response.out.write(template.render(path, template_values))
            return

        path = os.path.join(os.path.dirname(__file__),
            'templates/auth-new.html')
        self.response.out.write(template.render(path, template_values))

    def post(self):

        email = self.request.get("email", None)
        password = self.request.get("password", None)
        if not email or not password:
            logging.error("Missing email or password")
            self.redirect("/auth/admin/new?fail=1")
            return

        token = None
        try:
            ning_client = config.new_client()
            token = ning_client.login(email, password)
        except NingError, e:
            logging.error("Unable to get token: %s" % str(e))
            self.redirect("/auth/admin/new?fail=1")
            return

        if not token:
            logging.error("Can't add credntials: Missing token")
            self.redirect("/auth/admin/new?fail=1")
            return

        cred = Credential(token_key=token.key, token_secret=token.secret,
            owner=users.get_current_user(), email=email)
        cred.put()

        logging.info("Added new credentials: %s:%s" % (token.key,
            token.secret))
        self.redirect("/auth/admin/view?success=1")


class AuthBrowser(webapp.RequestHandler):

    def get(self):
        """Display the list of feeds"""

        credentials = []
        current_user = users.get_current_user()
        query = Credential.all().filter("owner =", current_user)

        for credential in query:
            credentials.append({
                "email": credential.email,
                "token_key": credential.token_key,
                "token_secret": credential.token_secret})


            path = os.path.join(os.path.dirname(__file__),
                'templates/auth-browse.html')
            template_values = {"credentials": credentials}
            self.response.out.write(template.render(path, template_values))
            return


def require_credentials(func):
    """Decorator that requires the user to have credentials"""

    def wrapper(self, *args, **kw):
        current_user = users.get_current_user()
        query = Credential.all().filter("owner =", current_user)
        if query.count() != 1:
            logging.warning("%s missing credentials, redirecting" %
                current_user.email())
            self.redirect("/auth/admin/new?unauthorized=1")
            return
        else:
            func(self, *args, **kw)

    return wrapper


def main():
    application = webapp.WSGIApplication([
            ('/auth/admin/new', AuthConfig),
            ('/auth/admin/view', AuthBrowser),
        ],
        debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
