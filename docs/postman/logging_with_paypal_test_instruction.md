## Paypal login test to our app
### Preparing first Postman request
If you have previously completed the order test, you should have the paypal_client_id and paypal_client_secret variables set up. If you don't have them set them up.
Add two new environment variables login_code and login_access_token. For now leave them blank.
Then:
POST https://api-m.sandbox.paypal.com/v1/oauth2/token
In authorization set the token just like it was done for oder test.
In body select format x-www-form-urlencoded and enter two rows as shown below:

key         | value

grant_type	| authorization_code
code	    | {{login_code}}

In Scripts in the After response section paste:
pm.environment.set("login_access_token", pm.response.json().access_token);
#### Do not send it yet, it was only preparation
### Logging to Paypal from our app link to get the login code
In your web browser enter:
https://www.sandbox.paypal.com/connect/?flowEntry=static&client_id=YOUR_CLIENT_ID&response_type=code&scope=openid&redirect_uri=https%3A%2F%2FLINK_TO_YOUR_SERVICE%2Fauth%2Fcallback&state=test123
Before be sure to change YOUR_CLIENT_ID to the Client_id variable and LINK_TO_YOUR_SERVICE as the proper link.

After entering, log in as one of the sandbox personal accounts.
It will then redirect you to our service, look at the address at the top and copy the value after code=

Then quicly paste it as the value of the login_code variable, as it is only valid for a short time.
### Send the prepared Postman request
You may now send the Postman request we prepared earlier.
If you get code 200 OK, the login_access_token should update automatically and you can go to the next step.
If You did not succeed it was probably due to the login_code expiring, try retrying the last step.
### Getting user info
GET https://api-m.sandbox.paypal.com/v1/identity/oauth2/userinfo?schema=paypalv1.1
In authorization choose Bearer token and enter {{login_access_token}} as the value.
The body section should be left as None.
After sending it, if you got status 200 OK, go to the response body. There you will be able to see the user credentials.
 

