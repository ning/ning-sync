Overview
========

Ning Sync is a [Google App Engine](http://code.google.com/appengine/)
application that allows syncing of external content into your Ning Network.
The server consumes [web feeds](http://en.wikipedia.org/wiki/Web_feeds) (aka
RSS, ATOM feeds), making it platform agnostic. One member can import content
from their WordPress blog, while another imports content from Blogger.

For example, let's say your Ning Network is about California politics and many
of your members have blogs that are relevant to the network. Each member of
the network can create an account on your Ning Sync server and have their blog
posts imported into your Ning Network under their account, automatically. To
other members, it will look as if they originally published the content on
your network.

Currently it supports the following features:

* RSS/ATOM feed => Blog Posts


Installing
==========

Ning Sync has the following dependencies that must be placed in the `lib`
directory:

* [Ning API Python Client](https://github.com/ning/ning-api-python)
* [Feed Parser](http://www.feedparser.org/)
* [httplib2](http://code.google.com/p/httplib2/)
* [iso8601](http://code.google.com/p/pyiso8601/)
* [oauth2](http://github.com/simplegeo/python-oauth2)
* [simplejson](http://code.google.com/p/simplejson/)

Once the dependencies have been installed, you must authorize Ning Sync to
talk to your Ning Network. You need to fill in the following values in
`config.py`:

* `NETWORK_NAME`
* `CONSUMER_KEY`
* `CONSUMER_SECRET`
* `NETWORK_SUBDOMAIN`

Change the `application` variable in `app.yaml` to match your App Engine
account.

Once configured, you can test the application using [Google App Engine
Launcher](http://code.google.com/appengine/downloads.html). After testing you
can deploy to Google App Engine.


Using
=====

To setup you first need to click the *Add your credentials* link on the main
page of the application. Any member type can setup an account on the server.

Once authorized, each member can click the *Add a feed* link. Once added, the
feed will be checked for new content every hour. When new content is available
it will automatically be uploaded to your Ning Network under the account the
member setup in the first step.


Contributing
============

Ning Sync is licensed under the Apache License, Version 2.0. We welcome
contributions and feedback via the [Ning Sync GitHub project
page](https://github.com/ning/ning-sync).
