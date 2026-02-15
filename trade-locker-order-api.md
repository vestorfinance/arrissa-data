Get non-final orders
get
https://demo.tradelocker.com/backend-api/trade/accounts/{accountId}/orders


Get non-final orders for the account. The column names are defined in the ordersConfig part of the /trade/config route

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
accountId
int32
required
Account identifier.

Query Params
from
int64
Unix timestamp in milliseconds (UTC) for the beginning of the interval. If not specified, all non-final orders are returned.

to
int64
Unix timestamp in milliseconds (UTC) for the end of the interval. If not specified, all non-final orders are returned.

tradableInstrumentId
int64
Instrument filter. If specified, only orders in this instrument will be returned.

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
orders
array of arrays of strings
orders

array of strings
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

Get list of instruments
Get orders history
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
/trade/accounts/{accountId}/orders
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/accounts/accountId/orders"
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
  "s": "ok",
3
  "d": {
4
    "orders": [
5
      [
6
        "7277816997907673698",
7
        "206",
8
        "1152263",
9
        "100.0",
10
        "sell",
11
        "limit",
12
        "New",
13
        null,
14
        null,
15
        "91011.74",
16
        null,
17
        "GTC",
18
        null,
19
        "1767886346666",
20
        "1767886346000",
21
        "true",
22
        null,
23
        null,
24
        null,
25
        null,
26
        null,
27
        null
28
      ],
29
      [
30
        "7277816997907673940",
31
        "206",
32
        "1152263",
33
        "100.0",
34
        "sell",
35
        "limit",
36
        "New",
37
        null,
38
        null,
39
        "91011.74",
40
        null,
41
        "GTC",
42
        null,
43
        "1767886397795",
44
        "1767886397000",
45
        "true",
46
        null,
47
        "91959.68",

Get orders history
get
https://demo.tradelocker.com/backend-api/trade/accounts/{accountId}/ordersHistory


Get orders history for an account. Returns all user's orders with a final status (rejected, filled, canceled). The column names are defined in the ordersHistoryConfig part of the /trade/config route

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
accountId
int32
required
Account identifier.

Query Params
from
int64
Unix timestamp in milliseconds (UTC) for the beginning of the interval. If not specified, all final orders are returned.

to
int64
Unix timestamp in milliseconds (UTC) for the end of the interval. If not specified, all final orders are returned.

tradableInstrumentId
int64
Instrument filter. If specified, only orders in this instrument will be returned.

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
ordersHistory
array of arrays of strings
ordersHistory

array of strings
hasMore
boolean
true if there is more data for the chosen timeframe

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

Get non-final orders
Get open positions
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
/trade/accounts/{accountId}/ordersHistory
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/accounts/accountId/ordersHistory"
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
    "ordersHistory": [
4
      [
5
        "7277816997907785466",
6
        "206",
7
        "1152263",
8
        "10.00",
9
        "sell",
10
        "market",
11
        "Filled",
12
        "10",
13
        "90263",
14
        "90300.67",
15
        "0",
16
        "IOC",
17
        null,
18
        "1767951991995",
19
        "1767951992000",
20
        "false",
21
        "7277816997846856994",
22
        null,
23
        null,
24
        null,
25
        null,
26
        ""
27
      ],
28
      [
29
        "7277816997907785465",
30
        "206",
31
        "1152263",
32
        "0.02",
33
        "sell",
34
        "market",
35
        "Filled",
36
        "0.02",
37
        "90300.33",
38
        "90301.02",
39
        "0",
40
        "IOC",
41
        null,
42
        "1767951991457",
43
        "1767951992000",
44
        "false",
45
        "7277816997846858693",
46
        null,
47
        null,

Get open positions
get
https://demo.tradelocker.com/backend-api/trade/accounts/{accountId}/positions


Get all currently open positions for an account. The column names are defined in the positionsConfig part of the /trade/config route

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
accountId
int32
required
Account identifier.

Headers
accNum
int32
required
Account number

Responses

200
Response body
object
d
object
required
positions
array of arrays of strings
array of strings
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

Get orders history
Get account's current details
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
/trade/accounts/{accountId}/positions
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/accounts/accountId/positions"
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
    "positions": [
4
      [
5
        "7277816997846858725",
6
        "206",
7
        "1152263",
8
        "buy",
9
        "10",
10
        "90415.16",
11
        null,
12
        null,
13
        "1767952099156",
14
        "-458.10",
15
        null
16
      ]
17
    ]
18
  },
19
  "s": "ok"
20
}

