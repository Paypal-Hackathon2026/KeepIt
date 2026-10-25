## Paypal sandbox order test in PLN on the Postman web app
## Before continuing ensure that in the Postman you have the 0Auth token set up and also set up your environmental variables
![alt text](image.png)
Instruction to recreate test:

### Create order
POST https://api-m.sandbox.paypal.com/v2/checkout/orders
In request body we choose raw and paste:
{
  "intent": "CAPTURE",
  "purchase_units": [
    {
      "custom_id": "challenge-1:alice",
      "amount": { "currency_code": "PLN", "value": "20.00" }
    }
  ],
  "payment_source": {
    "paypal": {
      "experience_context": {
        "return_url": "https://example.com/return",
        "cancel_url": "https://example.com/cancel",
        "user_action": "PAY_NOW"
      }
    }
  }
}
If the response is 200 OK, we copy the link in payer-action section of the response body.
### Confirming the order
With the link obtained in the previous step, we log as one of the personal paypal sandbox accounts.
After confirming the order, we can go to the next step.
### Capture
POST https://api-m.sandbox.paypal.com/v2/checkout/orders/{{order_id}}/capture
In body section we choose raw and leave it blank :{}
If the response was 201 Created we go to the next step. In the response body we can see the how much is the Paypal fee for this transaction.
### Confirming that the balance of the business account went up
Log in to the sandbox Paypal as our Business account, see the recent transaction.
If you can see it, go to the next step.
### Transfer from Business to user
POST https://api-m.sandbox.paypal.com/v1/payments/payouts
In body section choose raw and paste:
{
  "sender_batch_header": {
    "sender_batch_id": "pln-01",
    "email_subject": "Challenge reward"
  },
  "items": [
    {
      "recipient_type": "EMAIL",
      "amount": { "value": "10.00", "currency": "PLN" },
      "receiver": "{{email_for_test}}",
      "note": "Challenge completed",
      "sender_item_id": "pln-item-001"
    }
  ]
}
Remember to have an env variable saved for the email.
If the response was 201 Created, ensure you have an env var payout_batch_id and check if it updated to the payout_batch_id in the response body,then go to next step.
### Checking the status
GET https://api-m.sandbox.paypal.com/v1/payments/payouts/{{payout_batch_id}}
If the response was 200 OK, you can open the response body and check the status.
You may also log in to the Paypal sandbox account that the transfer went to to further verify that the transcaction was a success.


