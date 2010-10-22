import ningapi
import oauth2 as oauth

NETWORK_NAME = "API Example"
CONSUMER_KEY = "0d716e57-5ada-4b29-1459-2f4af1b26837"
CONSUMER_SECRET = "f0963fa5-324-434f-86fc-8a17d14b16ca"
NETWORK_SUBDOMAIN = "apiexample"

NING_API_URL = "https://external.ningapis.com"

def new_client(token=None):
    """Generate a new ningapi.Client instance"""

    consumer = oauth.Consumer(key=CONSUMER_KEY, secret=CONSUMER_SECRET)
    return ningapi.Client(NING_API_URL, NETWORK_SUBDOMAIN, consumer, token)
