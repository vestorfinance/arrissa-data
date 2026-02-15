Get account's current details
get
https://demo.tradelocker.com/backend-api/trade/accounts/{accountId}/state


Get current account state, such as balance, available funds, PnL, etc. Field names can be fetched from /config route.

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
OK

Response body
object
d
object
required
accountDetailsData
array of numbers
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

Get open positions
Trading
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
/trade/accounts/{accountId}/state
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/trade/accounts/accountId/state"
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
    "accountDetailsData": [
4
      392084.93,
5
      391415.43,
6
      389608.865,
7
      0,
8
      392084.93,
9
      0,
10
      389608.865,
11
      0,
12
      0,
13
      1806.965,
14
      1806.965,
15
      100,
16
      0,
17
      0,
18
      144,
19
      1806.965,
20
      389608.865,
21
      5725.99,
22
      5585.57,
23
      140.42,
24
      131.12,
25
      11,
26
      -669.5,
27
      -739.5,
28
      1,
29
      0
30
    ]
31
  },
32
  "s": "ok"
33
}

