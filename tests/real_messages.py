"""The plain messages real mode shows, word for word as approved."""

PHOTO_TIMEOUT = ("The photo check took too long to answer, so this result "
                 "skips it. Try again in a minute.")
PHOTO_NETWORK = ("Couldn't reach Google for the photo check, so this result "
                 "skips it. Check your connection and try again.")
PHOTO_REFUSED = ("Google turned down the photo check request, so this result "
                 "skips it. If it keeps happening, check GEMINI_API_KEY in "
                 "your .env file.")
PHOTO_LIMIT = ("Google's limit for your key was reached, so this result "
               "skips the photo check. Try again later.")
PHOTO_SERVER = ("Google had a problem on its side, so this result skips the "
                "photo check. Try again in a minute.")
PHOTO_CUT_OFF = ("The photo check answer was cut off, so this result skips "
                 "it. Try again.")
PHOTO_BLOCKED = ("Google blocked the photo check for this listing, so this "
                 "result skips it.")
PHOTO_SHAPE = ("The photo check answer came back in a form the tool can't "
               "read, so this result skips it. Try again.")
PHOTO_NO_MODEL = ("No Gemini Flash model is open to your key right now, so "
                  "this result skips the photo check.")

EBAY_SIGNIN_UNREACHABLE = ("Couldn't reach eBay to sign in. Check your "
                           "connection and try again.")
EBAY_SIGNIN_REFUSED = ("eBay turned down the sign-in. Check EBAY_CLIENT_ID "
                       "and EBAY_CLIENT_SECRET in your .env file.")
EBAY_SIGNIN_BAD_ANSWER = ("eBay's sign-in answer didn't make sense. Try "
                          "again in a minute.")
EBAY_SEARCH_FAILED = ("The eBay comp search failed, so there are no comps "
                      "this time. Try again in a minute.")
EBAY_LISTING_FAILED = ("Couldn't load that eBay listing. Check the link, or "
                       "enter the details by hand.")

ALL = [PHOTO_TIMEOUT, PHOTO_NETWORK, PHOTO_REFUSED, PHOTO_LIMIT, PHOTO_SERVER,
       PHOTO_CUT_OFF, PHOTO_BLOCKED, PHOTO_SHAPE, PHOTO_NO_MODEL,
       EBAY_SIGNIN_UNREACHABLE, EBAY_SIGNIN_REFUSED, EBAY_SIGNIN_BAD_ANSWER,
       EBAY_SEARCH_FAILED, EBAY_LISTING_FAILED]
