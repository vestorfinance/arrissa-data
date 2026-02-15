Get the historical bars
get
https://demo.tradelocker.com/backend-api/trade/history

Get the historical bars for an instrument. Any request that would result in a response with more than 20,000 bars will be rejected.
Each property of the response object is a table column. Bar time for daily bars is 00:00 UTC. Bar time for monthly bars is 00:00 UTC and is the first trading day of the month. If there is no data in the requested time period but there is data in the previous time period the status code will be set to no_data and the nb property to UNIX timestamp of the next available bar behind the range. If there is no data in the requested and previous time periods the status code will be set to no_data.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Query Params
routeId
int32
required
Route identifier.

from
int64
required
Unix timestamp in milliseconds (UTC) of the leftmost required bar, including from.

resolution
string
enum
required
Symbol resolution. Possible resolutions are monthly (1M), weekly (1W), daily (1D), hourly (4H, 1H) in minutes (30m, 15m, 5m, 1m)


1M

Show 9 enum values
to
int64
required
Unix timestamp in milliseconds (UTC) of the rightmost required bar, inclusive. If in the future, the rightmost returned bar will be the latest available in the system.

tradableInstrumentId
int64
required
Identifier of the instrument that is used for trading purposes.

Headers
accNum
int32
required
Account number

Responses

200
OK

Response body
object
d
object
required
barDetails
array of objects
Bar details

object
c
number
Close price.

h
number
High price.

l
number
Low price.

o
number
Open price.

t
int64
Unix timestamp in milliseconds (UTC) of the rightmost required bar, including to. It can be in the future. In this case, the rightmost required bar is the latest available bar.

v
number
Volume.

s
string
required
Status will always be ok.

401
Unauthorized

403
Forbidden

404
Not Found

Updated about 1 month ago

Get current daily bar
Get current prices
Did this page help you?
Language

Shell

Node

Ruby

PHP

Python
Credentials
Bearer
JWT
token

URL

https://demo.tradelocker.com/backend-api
/trade/history
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/history?resolution=1M"
4
​
5
headers = {"accept": "application/json"}
6
​
7
response = requests.get(url, headers=headers)
8
​
9
print(response.text)

Try It!
Response
1
{
2
  "d": {
3
    "barDetails": [
4
      {
5
        "c": 0,
6
        "h": 0,
7
        "l": 0,
8
        "o": 0,
9
        "t": 0,
10
        "v": 0
11
      }
12
    ]
13
  },
14
  "s": "ok"
15
}

