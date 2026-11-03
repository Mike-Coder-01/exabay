import requests



class MessagingClass ():
    def __init__(self, url, headers, body):
        self.url = url
        self.headers = headers
        self.body = body

    def send_sms (self):
        send_sms = requests.post(self.url, headers=self.headers, json=self.body)

        try:
            send_sms.raise_for_status()
            response_data = send_sms.json()
            print(response_data)

        except requests.exceptions.HTTPError as e:
            print("The api returned an error:", e)

        return None

    def fetch_sms_details_from_provider_server (self):
        get_sms_details = requests.get(self.url, headers=self.headers, json=self.body)

        try:
            get_sms_details.raise_for_status()
            response_data = get_sms_details.json()
            print(response_data)

        except requests.exceptions.HTTPError as e:
            print("The api returned an error:", e)

        return None