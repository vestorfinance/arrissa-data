Get instrument details
get
https://demo.tradelocker.com/backend-api/trade/instruments/{tradableInstrumentId}


Get detailed instrument settings, such as lot steps and sizes, quoting currency, trade session id, etc.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
tradableInstrumentId
int64
required
Identifier of the instrument that is used for trading purposes.

Query Params
routeId
int32
required
Route identifier

locale
string
enum
Locale (language) id.



Show 13 enum values
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
barSource
string
enum
The principle of building bars. Available values

ASK BID TRADE

baseCurrency
string
For currency pairs only. This field contains the first currency of the pair.

betSize
number
The standard bet size for the instrument with spreadbet type in units.

betStep
number
The minimal bet change of quantity in the betting currency. Required for spreadbet type symbols only.

bettingCurrency
string
The currency in which the instrument will be traded. Required for spreadbet type symbols only.

contractMonth
date
Final day for delivery.

country
int32
The country for the instrument.

deliveryStatus
string
enum
A contract delivery status.

DELIVERED READY_FOR_DELIVERY WAIT_FOR_PRICE

description
string
Any useful information about the instrument.

exerciseStyle
string
enum
Defines the date on which the option may be exercised.

AMERICAN EUROPEAN

firstTradeDate
date
The first day of trading on exchange

hasDaily
boolean
Boolean value showing whether the symbol includes daily bars historical data.

hasIntraday
boolean
Boolean value showing whether the symbol includes intraday (minutes) historical data.

industry
string
The Industry to which the instrument belongs.

isin
string
The International Securities Identification Number (ISIN) for the instrument.

lastTradeDate
date
The last day of trading on exchange. At the end of the session all orders will be canceled and positions will be blocked (a trader won't be able to close them).

leverage
number
Leverage

localizedName
string
The name of the instrument on the specified language in request.

logoUrl
string
URL to get instrument logo.

lotSize
number
The standard lot size for the instrument in units.

lotStep
number
The minimal lot quantity change.

margin_hedging_type
string
Margin hedging type

marketCap
double
The market capitalization of the Instrument.

marketDataExchange
string
required
The name of the exchange, which provides market data for the instrument.

maxLot
number
The largest allowed trade quantity in lots.

minLot
number
The smallest allowed trade quantity in lots.

name
string
required
Name of the instrument.

noticeDate
date
The date, when the server will send Futures notice email about the fact that contract is going to expire soon.

quotingCurrency
string
required
Symbol currency, also named as counter currency. If a symbol is a currency pair, then the currency field has to contain the second currency of this pair.

sector
string
The Sector to which the instrument belongs.

settlementDate
date
Settlement date of a contract.

settlementSystem
string
enum
The time between the trade date, when an order is executed in the market, and the settlement date.

Immediate SPOT SPOT+1 T+10 T+360 T+4 T+5 TOD TOM

strikePrice
number
Price at which a derivative contract can be bought or sold when it is exercised.

strikeType
string
enum
Put or Call

CALL PUT

symbolStatus
string
enum
required
Modes for trading.

CLOSED FULLY_OPEN TRADING_HALT

tickCost
array of objects
Amount of base asset for one tick.

object
leftRangeLimit
number
Left end of range.

tickCost
number
Amount of base asset for one tick.

tickSize
array of objects
Minimum price change for an instrument.

object
leftRangeLimit
number
Left end of range.

tickSize
number
Minimum price change for an instrument.

tradeSessionId
int32
Identifier of the instrument trade session

tradeSessionStatusId
int64
Identifier of the current status of the trade session for the instrument

tradingExchange
string
required
The name of the exchange, on which the instrument trade will be performed.

type
string
enum
required
Symbol type.

CRYPTO EQUITY EQUITY_CFD ETF FOREX FUTURES FUTURES_CFD INDICES OPTIONS SPREADBET

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

