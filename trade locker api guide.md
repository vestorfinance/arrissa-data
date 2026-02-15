Fetch JWT token
post
https://demo.tradelocker.com/backend-api/auth/jwt/token

Returns JWT accessToken and refreshToken.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.

Body Params
User credentials - email, password, server

email
string
required
User email

password
string
required
User password

server
string
required
Name of the broker server, also used during web login.

Responses

201
Created

Response body
object
accessToken
string
required
Access token for accessing /trade APIs.

refreshToken
string
required
Refresh token for refreshing JWT tokens.

expireDate
string
required
Access token expire date.

400
Bad Request

Updated about 1 month ago

Refresh JWT token
Did this page help you?
Language

Shell

Node

Ruby

PHP

Python
URL

https://demo.tradelocker.com/backend-api
/auth/jwt/token
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/auth/jwt/token"
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
response = requests.post(url, headers=headers)
11
​
12
print(response.text)

Try It!
Response
1
{
2
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJ0cmFkZWxvY2tlci1hcGkiLCJhdWQiOiJ0cmFkZWxvY2tlci1hcGktdHJhZGVycyIsInR5cGUiOiJhY2Nlc3NfdG9rZW4iLCJzdWIiOiJPU1AjREVWQ0xMOWc0aXNUT0VpS2pmTmRKdzEzIiwidWlkIjoiMTQ0YmYyODctNTFlNC00YjQyLWJlNTQtYzBkZTRmMTE3ODMzIiwiYnJhbmQiOiJPU1AiLCJpYXQiOjE2ODUxMTY3OTMsImV4cCI6MTY4NTEyMDM5M30.cyDXRqUNVX6h5rtZb7m30vNIwEoYN7xUU2jfGM-Cf90",
3
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJ0cmFkZWxvY2tlci1hcGkiLCJhdWQiOiJ0cmFkZWxvY2tlci1hcGktdHJhZGVycyIsInR5cGUiOiJyZWZyZXNoX3Rva2VuIiwic3ViIjoiT1NQI0RFVkNMTDlnNGlzVE9FaUtqZk5kSncxMyIsInVpZCI6IjE0NGJmMjg3LTUxZTQtNGI0Mi1iZTU0LWMwZGU0ZjExNzgzMyIsImJyYW5kIjoiT1NQIiwiaWF0IjoxNjg1MTE2NzkzLCJleHAiOjE2ODU3MjE1OTN9.GKNglolZzX76lKjTsrQ28MpmLTfU0A_T7vCMrsojLcg",
4
  "expireDate": "2023-05-26T16:59:53.000Z"
5
}


Refresh JWT token
post
https://demo.tradelocker.com/backend-api/auth/jwt/refresh

Generate new JWT accessToken and refreshToken

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.

Body Params
Refresh token

refreshToken
string
required
Refresh token for refreshing JWT tokens.

Responses

201
Returns accessToken and refreshToken

Response body
object
accessToken
string
required
Access token for accessing /trade APIs.

refreshToken
string
required
Refresh token for refreshing JWT tokens.

expireDate
string
required
Access token expire date.

400
Bad Request

Updated about 1 month ago

Fetch JWT token
List all accounts
Did this page help you?
Language

Shell

Node

Ruby

PHP

Python
URL

https://demo.tradelocker.com/backend-api
/auth/jwt/refresh
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/auth/jwt/refresh"
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
response = requests.post(url, headers=headers)
11
​
12
print(response.text)

Try It!
Response
1
{
2
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJ0cmFkZWxvY2tlci1hcGkiLCJhdWQiOiJ0cmFkZWxvY2tlci1hcGktdHJhZGVycyIsInR5cGUiOiJhY2Nlc3NfdG9rZW4iLCJzdWIiOiJPU1AjREVWQ0xMOWc0aXNUT0VpS2pmTmRKdzEzIiwidWlkIjoiMTQ0YmYyODctNTFlNC00YjQyLWJlNTQtYzBkZTRmMTE3ODMzIiwiYnJhbmQiOiJPU1AiLCJpYXQiOjE2ODUxMTY3OTMsImV4cCI6MTY4NTEyMDM5M30.cyDXRqUNVX6h5rtZb7m30vNIwEoYN7xUU2jfGM-Cf90",
3
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJ0cmFkZWxvY2tlci1hcGkiLCJhdWQiOiJ0cmFkZWxvY2tlci1hcGktdHJhZGVycyIsInR5cGUiOiJyZWZyZXNoX3Rva2VuIiwic3ViIjoiT1NQI0RFVkNMTDlnNGlzVE9FaUtqZk5kSncxMyIsInVpZCI6IjE0NGJmMjg3LTUxZTQtNGI0Mi1iZTU0LWMwZGU0ZjExNzgzMyIsImJyYW5kIjoiT1NQIiwiaWF0IjoxNjg1MTE2NzkzLCJleHAiOjE2ODU3MjE1OTN9.GKNglolZzX76lKjTsrQ28MpmLTfU0A_T7vCMrsojLcg",
4
  "expireDate": "2023-05-26T16:59:53.000Z"
5
}

List all accounts
get
https://demo.tradelocker.com/backend-api/auth/jwt/all-accounts

List all of the users accounts, find the accNum for making requests to the /trade api

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Responses

200
OK

Response body
object
accounts
array of objects
object
id
string
Account ID

name
string
Account Name

currency
string
Account currency

status
string
Account status

accNum
string
Account number - used to select the account on /trade API

aaccountBalance
number
Account balance

400
Bad Request

Updated about 1 month ago

Refresh JWT token
Account
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
/auth/jwt/all-accounts
Request
python -m pip install requests
1
import requests
2
​
3
url = "https://demo.tradelocker.com/backend-api/auth/jwt/all-accounts"
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
  "accounts": [
3
    {
4
      "id": "7080",
5
      "name": "BRAND1#DEVCLL9g4isTOEiKjfNdJw13#1#1",
6
      "currency": "USD",
7
      "status": "ACTIVE",
8
      "accNum": "1",
9
      "aaccountBalance": "2024.75"
10
    }
11
  ]
12
}

