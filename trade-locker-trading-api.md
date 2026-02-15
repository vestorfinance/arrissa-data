Place a new order
post
https://demo.tradelocker.com/backend-api/trade/accounts/{accountId}/orders


Place a new order.
Fields qty, routeId, side, validity, type, tradableInstrumentId are mandatory inside of the request body. Price can be set to 0 for market orders.

If using a stop type of order, you must specify the stopPrice.

Validity (also known as TimeInForce - TIF in some error messages) must be IOC for market orders and GTC for limit and stop orders.

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

Body Params
Request body with parameters

price
number
Limit Price for Limit order.

qty
number
required
The number of units to open the buy or sell order.

routeId
number
required
Identifier of the trade connection. Find the corresponding INFO or TRADE routeId by querying the /trade/accounts/{accountId}/instruments endpoint.

side
string
enum
required
Order side. If the creating order is a closing one for the position, then the side must be opposite to the side of the position


buy
Allowed:

buy

sell
strategyId
string
Arbitrary string (up to 31 chars) that can be attached to identify orders and positions placed through algorithmic trading. This value will also be visible in GET /orders, GET /ordersHistory, and GET /positions.

stopLoss
number
Stop loss amount for the order. Must be specified in case of absolute or offset stop loss type.

stopLossType
string
enum
Type of stop loss price for the order. Available types: absolute, offset, trailingOffset.


Allowed:

absolute

offset

trailingOffset
stopPrice
number
Stop Price for Stop orders.

takeProfit
number
TakeProfit amount for the order. Must be specified together with the takeProfitType field. Specifies either the absolute price, or an offset in pips.

takeProfitType
string
enum
Type of take profit for the order. Available types: [absolute, offset]. Must be specified together with the takeProfit field.


Allowed:

absolute

offset
trStopOffset
number
For the 'trailingOffset' stopLossType. The trailing offset in pips.

tradableInstrumentId
int64
required
Identifier of the instrument that is used for trading purposes.

type
string
enum
required
Order type. Available types: limit, market, stop. If using a stop order, the stopPrice field must be specified. If using a limit order, the price field must be specified. If using a market order, the price field is ignored.


limit
Allowed:

limit

market

stop
validity
string
enum
required
Whether the order is Good Till Cancelled (GTC) or Immediate or Cancel (IOC). For market orders, use IOC, otherwise, use GTC. In error messages, Validity is sometimes referred to as TimeInForce (TIF).


GTC
Allowed:

GTC

IOC
Headers
accNum
int32
required
Account number

developer-api-key
string
developer-api-key

Responses

200
OK

Response body
object
d
object
required
orderId
string
New order identifier.

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

Get account's current details
Cancel all orders
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
payload = {
6
    "side": "buy",
7
    "type": "limit",
8
    "validity": "GTC"
9
}
10
headers = {
11
    "accept": "application/json",
12
    "content-type": "application/json"
13
}
14
​
15
response = requests.post(url, json=payload, headers=headers)
16
​
17
print(response.text)

Try It!
Response
1
{
2
  "d": {
3
    "orderId": "123"
4
  },
5
  "s": "ok"
6
}

Cancel all orders
delete
https://demo.tradelocker.com/backend-api/trade/accounts/{accountId}/orders


Cancel all existing orders.

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
tradableInstrumentId
int64
Instrument filter. If specified, only orders in this instrument will be deleted.

Headers
accNum
int32
required
Account number

developer-api-key
string
developer-api-key

Responses

200
Response body
object
s
string
required
Status will always be ok.

204
No Content

401
Unauthorized

403
Forbidden

Updated about 1 month ago

Place a new order
Close all positions
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
response = requests.delete(url, headers=headers)
8
​
9
print(response.text)

Try It!
Response
1
{
2
  "s": "ok"
3
}

Close all positions
delete
https://demo.tradelocker.com/backend-api/trade/accounts/{accountId}/positions


Place closing orders for all open positions. Isn't guaranteed to close all positions, or close them immediately. Will attempt to place an IOC, then GTC closing order, so the execution might be delayed.

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
tradableInstrumentId
int64
Instrument filter. If specified, only positions in this instrument will be closed.

strategyId
string
Strategy ID

Headers
accNum
int32
required
Account number

developer-api-key
string
developer-api-key

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

Cancel all orders
Cancel an existing order
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
response = requests.delete(url, headers=headers)
8
​
9
print(response.text)

Try It!
Response
1
{
2
  "s": "ok"
3
}

Cancel an existing order
delete
https://demo.tradelocker.com/backend-api/trade/orders/{orderId}


Cancel an existing order. Only available before an order is executed.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
orderId
int64
required
Order identifier.

Headers
accNum
int32
required
Account number

developer-api-key
string
developer-api-key

Responses

200
Response body
object
s
string
required
Status will always be ok.

204
No Content

401
Unauthorized

403
Forbidden

Updated about 1 month ago

Close all positions
Modify an existing order
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
/trade/orders/{orderId}
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/orders/orderId"
4
​
5
headers = {"accept": "application/json"}
6
​
7
response = requests.delete(url, headers=headers)
8
​
9
print(response.text)

Try It!
Response
1
{
2
  "s": "ok"
3
}

Modify an existing order
patch
https://demo.tradelocker.com/backend-api/trade/orders/{orderId}


Modify an existing order.

For more details on each of the fields in the body, look at their definitions in the POST /trade/accounts/{accountId}/orders route.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
orderId
int64
required
Order identifier.

Body Params
Request body with parameters

price
number
qty
number
stopLoss
number
stopLossType
string
enum

Allowed:

absolute

offset

trailingOffset
stopPrice
number
takeProfit
number
takeProfitType
string
enum

Allowed:

absolute

offset
trStopOffset
number
validity
string
enum

Allowed:

GTC

IOC
Headers
accNum
int32
required
Account number

developer-api-key
string
developer-api-key

Responses

200
OK

Response body
object
d
array of arrays of strings
required
modifiedOrder

array of strings
s
string
required
Status will always be ok.

204
No Content

401
Unauthorized

403
Forbidden

Updated about 1 month ago

Cancel an existing order
Close a position
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
/trade/orders/{orderId}
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/orders/orderId"
4
​
5
headers = {
6
    "accept": "application/json",
7
    "content-type": "application/json"
8
}
9
​
10
response = requests.patch(url, headers=headers)
11
​
12
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
        "7277816997907787135",
7
        "206",
8
        "1152263",
9
        "10.0",
10
        "buy",
11
        "limit",
12
        "None",
13
        null,
14
        null,
15
        "89800",
16
        null,
17
        "GTC",
18
        null,
19
        "1767953209489",
20
        "1767953257000",
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
      ]
29
    ]
30
  }
31
}

Close a position
delete
https://demo.tradelocker.com/backend-api/trade/positions/{positionId}


Place an order to close an existing position. Isn't guaranteed to close the positions, or close it immediately. Will attempt to place an IOC, then GTC closing order, so the execution might be delayed. If you want to fully close position set parameter qty to 0, but if you want to partially close a position just set the qty parameter to the number of lots that you want to close.

NOTE: if you don't know what is the positionId value (you only have an orderId of the order that opened the position), you can use the GET /trade/accounts/{accountId}/ordersHistory route to get the list of all final orders and their IDs. Just match the orderId with the positionId.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
positionId
int64
required
Position identifier.

Query Params
strategyId
string
Strategy ID

Body Params
Request body with parameters

qty
number
Headers
accNum
int32
required
Account number

developer-api-key
string
developer-api-key

Responses

200
Response body
object
s
string
required
Status will always be ok.

204
No Content

401
Unauthorized

403
Forbidden

Updated about 1 month ago

Modify an existing order
Modify position
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
/trade/positions/{positionId}
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/positions/positionId"
4
​
5
headers = {
6
    "accept": "application/json",
7
    "content-type": "application/json"
8
}
9
​
10
response = requests.delete(url, headers=headers)
11
​
12
print(response.text)

Try It!
Response
1
{
2
  "s": "ok"
3
}

Modify position
patch
https://demo.tradelocker.com/backend-api/trade/positions/{positionId}


Modify an existing position's stop loss, take profit, or both. To remove stop loss or take profit you need to set the parameter to null.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
positionId
int64
required
Position identifier.

Query Params
strategyId
string
Strategy ID

Body Params
Request body with parameters

stopLoss
number
takeProfit
number
trailingOffset
number
Headers
accNum
int32
required
Account number

developer-api-key
string
developer-api-key

Responses

200
Response body
object
s
string
required
Status will always be ok.

204
No Content

401
Unauthorized

403
Forbidden

Updated about 1 month ago

Close a position
Config
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
/trade/positions/{positionId}
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/positions/positionId"
4
​
5
headers = {
6
    "accept": "application/json",
7
    "content-type": "application/json"
8
}
9
​
10
response = requests.patch(url, headers=headers)
11
​
12
print(response.text)

Try It!
Response
1
{
2
  "s": "ok"
3
}

