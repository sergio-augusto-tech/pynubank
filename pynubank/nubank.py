import uuid
from typing import Tuple

from qrcode import QRCode

from pynubank.utils.discovery import Discovery
from pynubank.utils.http import HttpClient
from pynubank.utils.graphql import prepare_request_body

PAYMENT_EVENT_TYPES = (
    'TransferOutEvent',
    'TransferInEvent',
    'TransferOutReversalEvent',
    'BarcodePaymentEvent',
    'DebitPurchaseEvent',
    'DebitPurchaseReversalEvent',
    'BillPaymentEvent',
    'DebitWithdrawalFeeEvent',
    'DebitWithdrawalEvent'
)


class Nubank:
    feed_url = None
    query_url = None
    bills_url = None

    def __init__(self, client=HttpClient()):
        self.client = client
        self.discovery = Discovery(self.client)

    def _make_graphql_request(self, graphql_object, variables=None):
        return self.client.post(self.query_url,
                                json=prepare_request_body(graphql_object, variables))

    def _password_auth(self, cpf: str, password: str):
        payload = {
            "grant_type": "password",
            "login": cpf,
            "password": password,
            "client_id": "other.conta",
            "client_secret": "yQPeLzoHuJzlMMSAjC-LgNUJdUecx8XO"
        }
        return self.client.post(self.discovery.get_url('login'), json=payload)

    def _save_auth_data(self, auth_data: dict) -> None:
        self.client.set_header('Authorization', f'Bearer {auth_data["access_token"]}')
        self.feed_url = auth_data['_links']['events']['href']
        self.query_url = auth_data['_links']['ghostflame']['href']
        self.bills_url = auth_data['_links']['bills_summary']['href']

    def get_qr_code(self) -> Tuple[str, QRCode]:
        content = str(uuid.uuid4())
        qr = QRCode()
        qr.add_data(content)
        return content, qr

    def authenticate_with_qr_code(self, cpf: str, password, uuid: str):
        auth_data = self._password_auth(cpf, password)
        self.client.set_header('Authorization', f'Bearer {auth_data["access_token"]}')

        payload = {
            'qr_code_id': uuid,
            'type': 'login-webapp'
        }

        response = self.client.post(self.discovery.get_app_url('lift'), json=payload)

        self._save_auth_data(response)

    def authenticate_with_cert(self, cpf: str, password: str, cert_path: str):
        self.client.set_cert(cert_path)
        url = self.discovery.get_app_url('token')
        payload = {
            'grant_type': 'password',
            'client_id': 'legacy_client_id',
            'client_secret': 'legacy_client_secret',
            'login': cpf,
            'password': password
        }

        response = self.client.post(url, json=payload)

        self._save_auth_data(response)

        return response.get('refresh_token')

    def authenticate_with_refresh_token(self, refresh_token: str, cert_path: str):
        self.client.set_cert(cert_path)

        url = self.discovery.get_app_url('token')
        payload = {
            'grant_type': 'refresh_token',
            'client_id': 'legacy_client_id',
            'client_secret': 'legacy_client_secret',
            'refresh_token': refresh_token,
        }

        response = self.client.post(url, json=payload)

        self._save_auth_data(response)

    def get_card_feed(self):
        return self.client.get(self.feed_url)

    def get_card_statements(self):
        feed = self.get_card_feed()
        return list(filter(lambda x: x['category'] == 'transaction', feed['events']))

    def get_bills(self):
        request = self.client.get(self.bills_url)
        return request['bills']

    def get_bill_details(self, bill: dict):
        return self.client.get(bill['_links']['self']['href'])

    def get_account_feed(self):
        data = self._make_graphql_request('account_feed')
        return data['data']['viewer']['savingsAccount']['feed']

    def get_account_statements(self):
        feed = self.get_account_feed()
        return list(filter(lambda x: x['__typename'] in PAYMENT_EVENT_TYPES, feed))

    def get_account_balance(self):
        data = self._make_graphql_request('account_balance')
        return data['data']['viewer']['savingsAccount']['currentSavingsBalance']['netAmount']

    def get_account_investments_details(self):
        data = self._make_graphql_request('account_investments')
        return data['data']['viewer']['savingsAccount']['redeemableDeposits']

    def create_boleto(self, amount: float) -> str:
        customer_id_response = self._make_graphql_request('account_id')
        customer_id = customer_id_response['data']['viewer']['id']

        payload = {
            "input": {"amount": str(amount), "customerId": customer_id}
        }

        boleto_response = self._make_graphql_request('create_boleto', payload)

        barcode = boleto_response['data']['createTransferInBoleto']['boleto']['readableBarcode']

        return barcode

    def create_money_request(self, amount: float) -> str:
        account_data = self._make_graphql_request('account_feed')
        account_id = account_data['data']['viewer']['savingsAccount']['id']
        payload = {
            'input': {
                'amount': amount, 'savingsAccountId': account_id
            }
        }

        money_request_response = self._make_graphql_request('create_money_request', payload)

        return money_request_response['data']['createMoneyRequest']['moneyRequest']['url']
