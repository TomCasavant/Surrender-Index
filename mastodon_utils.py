from mastodon import Mastodon
import os
import toml

class MastodonBot:

    def __init__(self, config_path='config.toml') -> None:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_path)
        with open(config_path, 'r') as config_file:
            self.config = toml.load(config_file)
            self.server = self.config.get("server")
            self.access_token = self.config.get("access_token")
            self.mastodon = self.login()

    def login(self):
        print("Logged in")
        return Mastodon(access_token=self.access_token, api_base_url=self.server)

    def post(self, message, reply_id=None, poll=None):
        print("Posting status...")
        return self.mastodon.status_post(message, in_reply_to_id=reply_id, poll=poll, language='en')
    
    def get_poll_result(self, poll_id):
        print("Getting poll result")
        poll_status = self.mastodon.status(poll_id)
        return poll_status.poll["options"]

    def make_simple_poll(self, options=[], hide_totals=False, expires_in=60*60):
        return self.mastodon.make_poll(
            options, expires_in=expires_in, hide_totals=False
        )
    
    def delete_status(self, status_id):
        print(f"Deleting status with ID: {status_id}")
        return self.mastodon.status_delete(status_id)

    def boost(self, status_id):
        print(f"Boosting status with ID: {status_id}")
        return self.mastodon.status_reblog(status_id)

    def unboost(self, status_id):
        print(f"Unboosting status with ID: {status_id}")
        return self.mastodon.status_unreblog(status_id)

        