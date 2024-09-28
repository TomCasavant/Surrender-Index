from dateutil import parser, tz
from datetime import timezone, timedelta, datetime
import pytz 

class NFLGame:

    game_summary = {}

    def __init__(self, event_info):
        self.event_info = event_info

    def get_now(self):
        return datetime.now(tz=tz.gettz())

    @property
    def id(self): 
        return self.event_info['id']
 
    @property
    def game_time(self):
        game_date = parser.parse(self.event_info['date'])
        return game_date.replace(tzinfo=timezone.utc).astimezone(tz=None)

    @property
    def is_starting_soon(self):
        now = self.get_now() #datetime.now(timezone.utc).astimezone(tz=None)  # Make 'now' aware and in local timezone
        return self.game_time - timedelta(minutes=15) < now < self.game_time + timedelta(hours=6)

    @property
    def drives(self):
        return self.game_summary.get('drives', {}) if self.game_summary else {}

    @property
    def is_final(self):
        return (
            self.game_summary.get('header', {}).get('competitions', [{}])[0].get('status', {}).get('type', {}).get('name') == 'STATUS_FINAL'
        )

    @property
    def is_postseason(self):
        return self.game_summary.get('header', {}).get('season', {}).get('type', 0) > 2

        
    @property
    def previous_drives(self):
        return self.drives.get('previous', [])

    def update_game_summary(self, session):
        """
        Update the game summary from the ESPN API.

        Parameters:
            session: An active requests.Session object for making the API call.
        """
        base_link = "http://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event="
        game_link = f"{base_link}{self.id}"

        try:
            response = session.get(game_link, timeout=10)
            response.raise_for_status()  # Raise an error for bad responses
            self.game_summary = response.json()

        except requests.RequestException as e:
            print(f"An error occurred while fetching game summary: {e}")