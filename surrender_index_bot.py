"""
Andrew Shackelford
andrewshackelford97@gmail.com
@shackoverflow

surrender_index_bot.py
A Twitter bot that tracks every live game in the NFL,
and tweets out the "Surrender Index" of every punt
as it happens.

Inspired by SB Nation's Jon Bois @jon_bois.

Restructured and setup for Mastodon by @tom@tomkahe.com
"""

import argparse
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from dateutil import parser, tz
import espn_scraper as espn
import json
import numpy as np
import os
import pickle
import requests
from requests.adapters import HTTPAdapter, Retry
import scipy.stats as stats
from subprocess import Popen, PIPE
import sys
import threading
import time
import traceback
import time
from datetime import datetime
import pytz
from mastodon_utils import MastodonBot
from surrender_index import SurrenderIndex
from nfl_game import NFLGame

# A dictionary of plays that have already been tweeted.
tweeted_plays = None

# A dictionary of the currently active games.
games = {}

# The authenticated Tweepy APIs.
api, ninety_api = None, None

# NPArray of historical surrender indices.
historical_surrender_indices = None

# Whether the bot should tweet out any punts
should_tweet = True

### SELENIUM FUNCTIONS ###


### PERCENTILE FUNCTIONS ###
class SurrenderIndexBot:
    def __init__(self):
        self.tweeted_plays = {}
        self.games = {}
        self.api = None
        self.ninety_api = None
        self.historical_surrender_indices = None
        self.should_tweet = True
        self.should_text = True
        self.enable_main_account = True
        self.reply_using_tweepy = True
        self.notify_using_twilio = False
        self.debug = False
        self.not_headless = False
        self.enable_cancel = False
        self.sleep_time = 1
        self.seen_plays = {}
        self.gmail_client = None
        self.twilio_client = None
        self.completed_game_ids = set()
        self.final_games = set()
        self.session = None
        self.mastodon_acc = MastodonBot()
        self.mastodon_acc_90 = MastodonBot("ninety_config.toml")
        
        # Load historical surrender indices
        self.historical_surrender_indices = self.load_historical_surrender_indices()
    
    ### TEAM ABBREVIATION FUNCTIONS ###

    def get_home_team(self, game):
        return game.game_summary['boxscore']['teams'][1]['team']['abbreviation']


    def get_away_team(self, game):
        return game.game_summary['boxscore']['teams'][0]['team']['abbreviation']


    def return_other_team(self, game, team):
        return self.get_away_team(game) if self.get_home_team(
            game) == team else self.get_home_team(game)

    def get_active_game_ids(self):
        now = self.get_now()
        active_game_ids = set()

        for game in self.current_week_games:
            if game.id in self.completed_game_ids:
                continue
            if game.is_starting_soon:
                active_game_ids.add(game)

        return active_game_ids
    
    def time_print(self, message):
        print(self.get_current_time_str() + ": " + str(message))

    def get_current_time_str(self):
        return datetime.now().strftime("%b %-d at %-I:%M:%S %p")
    
    def send_error_message(self, e, body="An error occurred"):
        print(e)
        #TODO: Add method to alert maintainer of error
        #if self.should_text:
        #    self.send_message(body + ": " + str(e) + ".")

    def download_data_for_active_games(self):
        active_game_ids = self.get_active_game_ids()
        if len(active_game_ids) == 0:
            time_print("No games active. Sleeping for 15 minutes...")
            time.sleep(14 * 60)  # We sleep for another minute in the live callback

        for game in active_game_ids:
            game.update_game_summary(self.session)

        self.live_callback()

    def cancel_punt(self, orig_status, full_text):
        self.mastodon_acc_90.unboost(orig_status['id'])
        self.mastodon_acc_90.post('CANCELED', reply_id=orig_status['id'])

    def handle_cancel(self, orig_status, full_text):
        # Post poll in reply to original status
        options = ['Yes', 'No']
        poll = self.mastodon_acc.make_simple_poll(options)
        status = self.mastodon_acc_90.post("Should this punt's Surrender Index be canceled?", reply_id=orig_status['id'], poll=poll)
        
        if self.check_reply(status):
            self.cancel_punt(orig_status, full_text)

    def check_reply(self, poll_status):
        time.sleep(5 * 60)  # Wait one hour and one minute to check reply
        poll_results = self.mastodon_acc_90.get_poll_result(poll_status['id'])

        total_votes = sum(option['votes_count'] for option in poll_results)

        # Check if the total number of votes is greater than 2 
        if total_votes > 2:
            for option in poll_results:
                if option['title'].lower() == 'yes':
                    yes_percentage = (option['votes_count'] / total_votes) * 100
                    # Return True if 'Yes' has more than 66.67%
                    if yes_percentage >= 66.67:
                        return True

        return False

    def get_now(self):
        # Set the desired time for testing: Thursday, September 26th, 2024 at 9 PM EST
        est = pytz.timezone('US/Eastern')
        test_time = datetime(2024, 9, 26, 21, 0, 0)  # 9 PM on September 26, 2024
        return est.localize(test_time)  # Localize to Eastern Time

    def update_current_week_games(self):
        self.current_week_games = []

        espn_data = requests.get(
            "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
            timeout=10).json()

        for event in espn_data['events']:
            self.current_week_games.append(NFLGame(event))

    def get_possessing_team(self, play, game):
        team_id = play.get('start', {}).get('team', {}).get('id')
        if not team_id:
            team_id = play.get('end', {}).get('team', {}).get('id')
        for team in game.game_summary['boxscore']['teams']:
            if team['team']['id'] == team_id:
                return team['team']['abbreviation']

    def is_punt(self, drive):
        return 'punt' in drive.get('result', '').lower()

    def get_qtr_num(self, play):
        return play['period']['number']

    def has_been_tweeted(self, drive, game_id):
        game_plays = self.tweeted_plays.get(game_id, [])
        return drive.get('id', '') in game_plays

    def has_been_seen(self, drive, game_id):
        game_plays = self.seen_plays.get(game_id, [])
        if drive.get('id', '') in game_plays:
            return True
        game_plays.append(drive.get('id', ''))
        self.seen_plays[game_id] = game_plays
        return False

    def has_been_final(self, game_id):
        if game_id in self.final_games:
            return True
        self.final_games.add(game_id)
        return False

    def load_tweeted_plays_dict(self):
        self.tweeted_plays = {}
        if os.path.exists('tweeted_plays.json'):
            file_mod_time = os.path.getmtime('tweeted_plays.json')
        else:
            file_mod_time = 0.
        if time.time() - file_mod_time < 60 * 60 * 12:
            with open('tweeted_plays.json', 'r') as f:
                self.tweeted_plays = json.load(f)
        else:
            with open('tweeted_plays.json', 'w') as f:
                json.dump(self.tweeted_plays, f)

    def update_tweeted_plays(self, drive, game_id):
        game_plays = self.tweeted_plays.get(game_id, [])
        game_plays.append(drive['id'])
        self.tweeted_plays[game_id] = game_plays
        with open('tweeted_plays.json', 'w') as f:
            json.dump(self.tweeted_plays, f)


    def create_tweet_str(self, play,
                        prev_play,
                        drive,
                        game,
                        surrender_index,
                        current_percentile,
                        historical_percentile,
                        delay_of_game=False):
        territory_str = play['start']['possessionText']
        asterisk = '*' if delay_of_game else ''

        decided_str = self.get_possessing_team(
            play, game) + ' decided to punt to ' + self.return_other_team(
                game, self.get_possessing_team(play, game))
        yrdln_str = ' from the ' + territory_str + asterisk + ' on '
        down_str = play['start']['shortDownDistanceText'] + asterisk
        clock_str = ' with ' + play['clock']['displayValue'] + ' remaining in '
        qtr_str = get_qtr_str(play['period']['number']) + \
            ' while ' + get_score_str(prev_play, game) + '.'

        play_str = decided_str + yrdln_str + down_str + clock_str + qtr_str

        surrender_str = 'With a Surrender Index of ' + str(
            round(surrender_index, 2)
        ) + ', this punt ranks at the ' + self.get_num_str(
            current_percentile
        ) + ' percentile of cowardly punts of the 2024 season, and the ' + self.get_num_str(
            historical_percentile) + ' percentile of all punts since 1999.'

        return play_str + '\n\n' + surrender_str
    
    def tweet_play(self, play, prev_play, drive, game, game_id):
        enable_cancel = True
        delay_of_game = self.is_delay_of_game(play, prev_play) 

        if delay_of_game:
            updated_play = play.copy()
            updated_play['start'] = prev_play['start']
            updated_play['end'] = prev_play['end']

            surrender_index = SurrenderIndex.calc_surrender_index(
                updated_play, prev_play, drive, game)

            current_percentile, historical_percentile = calculate_percentiles(
                surrender_index)

            unadjusted_surrender_index = SurrenderIndex.calc_surrender_index(
                play, prev_play, drive, game)

            unadjusted_current_percentile, unadjusted_historical_percentile = self.calculate_percentiles(
                unadjusted_surrender_index, should_update_file=False)

            tweet_str = self.create_tweet_str(updated_play, prev_play, drive, game,
                                        surrender_index, current_percentile,
                                        historical_percentile, delay_of_game)
        else:
            surrender_index = SurrenderIndex.calc_surrender_index(play, prev_play, drive, game)
            current_percentile, historical_percentile = self.calculate_percentiles(
                surrender_index)
            tweet_str = self.create_tweet_str(play, prev_play, drive, game,
                                        surrender_index, current_percentile,
                                        historical_percentile, delay_of_game)

        self.time_print(tweet_str)

        if delay_of_game:
            delay_of_game_str = self.create_delay_of_game_str(
                play, drive, game, prev_play, unadjusted_surrender_index,
                unadjusted_current_percentile, unadjusted_historical_percentile)
            self.time_print(delay_of_game_str)

        main_status = None
        if self.should_tweet and self.enable_main_account:
            if True:
                main_status = self.mastodon_acc.post(tweet_str)

        # Post the status to the 90th percentile account.
        if current_percentile >= 70. and should_tweet:
            status = self.mastodon_acc_90.boost(main_status['id'])
            if delay_of_game:
                #print(delay_of_game_str)
                self.mastodon_acc.post(delay_of_game_str, reply_id=main_status['id'])
            if enable_cancel:
                thread = threading.Thread(target=self.handle_cancel,
                                        args=(status, tweet_str))
                thread.start()

        self.update_tweeted_plays(drive, game_id)

    def get_qtr_str(self, qtr):
        if qtr <= 4:
            return 'the ' + str(qtr) + self.get_ordinal_suffix(qtr)
        elif qtr == 5:
            return 'OT'
        elif qtr == 6:
            return '2 OT'
        elif qtr == 7:
            return '3 OT'
        return ''


    def get_ordinal_suffix(self, num):
        last_digit = str(num)[-1]
        if last_digit == '1':
            return 'st'
        elif last_digit == '2':
            return 'nd'
        elif last_digit == '3':
            return 'rd'
        else:
            return 'th'

    def load_historical_surrender_indices(self):
        with open('1999-2024_surrender_indices.npy', 'rb') as f:
            return np.load(f)


    def load_current_surrender_indices(self):
        try:
            with open('current_surrender_indices.npy', 'rb') as f:
                return np.load(f)
        except BaseException:
            return np.array([])


    def write_current_surrender_indices(self, surrender_indices):
        with open('current_surrender_indices.npy', 'wb') as f:
            np.save(f, surrender_indices)


    def calculate_percentiles(self, surrender_index, should_update_file=True):

        current_surrender_indices = self.load_current_surrender_indices()
        current_percentile = stats.percentileofscore(current_surrender_indices,
                                                    surrender_index,
                                                    kind='strict')
        if np.isnan(current_percentile):
            current_percentile = 100.

        all_surrender_indices = np.concatenate(
            (historical_surrender_indices, current_surrender_indices))
        historical_percentile = stats.percentileofscore(all_surrender_indices,
                                                        surrender_index,
                                                        kind='strict')

        if self.should_update_file:
            current_surrender_indices = np.append(current_surrender_indices,
                                                surrender_index)
            self.write_current_surrender_indices(current_surrender_indices)

        return current_percentile, historical_percentile



    def create_delay_of_game_str(self, play, drive, game, prev_play,
                                unadjusted_surrender_index,
                                unadjusted_current_percentile,
                                unadjusted_historical_percentile):
        new_territory_str = play['start']['possessionText']
        old_territory_str = prev_play['start']['possessionText']

        penalty_str = "*" + self.get_possessing_team(
            play,
            game) + " committed a (likely intentional) delay of game penalty, "
        old_yrdln_str = "moving the play from " + \
            prev_play['start']['shortDownDistanceText'] + \
            " at the " + prev_play['start']['possessionText']
        new_yrdln_str = " to " + play['start']['shortDownDistanceText'] + \
            " at the " + play['start']['possessionText'] + ".\n\n"
        index_str = "If this penalty was in fact unintentional, the Surrender Index would be " + \
            str(round(unadjusted_surrender_index, 2)) + ", "
        percentile_str = "ranking at the " + self.get_num_str(
            unadjusted_current_percentile) + " percentile of the 2024 season."

        return penalty_str + old_yrdln_str + new_yrdln_str + index_str + percentile_str
        
    def get_num_str(self, num):
        rounded_num = int(num)  # round down
        if rounded_num % 100 == 11 or rounded_num % 100 == 12 or rounded_num % 100 == 13:
            return str(rounded_num) + 'th'

        # add more precision for 99th percentile
        if rounded_num == 99:
            if num < 99.9:
                return str(round(num, 1)) + self.get_ordinal_suffix(round(num, 1))
            elif num < 99.99:
                return str(round(num, 2)) + self.get_ordinal_suffix(round(num, 2))
            else:
                # round down
                multiplied = int(num * 1000)
                rounded_down = float(multiplied) / 1000
                return str(rounded_down) + self.get_ordinal_suffix(rounded_down)

        return str(rounded_num) + self.get_ordinal_suffix(rounded_num)


    def pretty_score_str(self, score_1, score_2):
        if score_1 > score_2:
            ret_str = 'winning '
        elif score_2 > score_1:
            ret_str = 'losing '
        else:
            ret_str = 'tied '

        ret_str += str(score_1) + ' to ' + str(score_2)
        return ret_str


    def get_score_str(self, play, game):
        if self.get_possessing_team(play, game) == get_home_team(game):
            return self.pretty_score_str(play['homeScore'], play['awayScore'])
        else:
            return self.pretty_score_str(play['awayScore'], play['homeScore'])

    def is_delay_of_game(self, play, prev_play):
        return 'delay of game' in prev_play['text'].lower(
        ) and self.get_dist_num(play) - self.get_dist_num(prev_play) > 0


    def live_callback(self):
        active_game_ids = self.get_active_game_ids()
        start_time = time.time()
        for game in active_game_ids:
            self.time_print('Getting data for game ID ' + game.id)
            for index, drive in enumerate(game.previous_drives):
                if 'result' not in drive:
                    continue

                drive_plays = drive.get('plays', [])
                if len(drive_plays) < 2:
                    continue

                if not self.is_punt(drive):
                    continue

                if self.has_been_tweeted(drive, game.id):
                    continue

                if not self.has_been_seen(drive, game.id):
                    continue

                punt = None
                for index, play in enumerate(drive_plays):
                    if index == 0:
                        continue
                    if 'punt' in play.get('type', {}).get('text', '').lower():
                        punt = play
                        prev_play = drive_plays[index - 1]

                if not punt:
                    punt = drive_plays[-1]
                    prev_play = drive_plays[-2]

                try:
                    self.tweet_play(punt, prev_play, drive, game, game.id)
                except BaseException as e:
                    traceback.print_exc()
                    self.time_print("Error occurred:")
                    self.time_print(e)
                    error_str = "Failed to tweet play from drive " + \
                        drive.get('id', '')
                    self.time_print(error_str)
                    self.send_error_message(e, error_str)

            if game.is_final:
                if self.has_been_final(game.id):
                    self.completed_game_ids.add(game.id)
        while (time.time() < start_time + 30):
            time.sleep(1)
        print("")

    def run(self):
        parser = argparse.ArgumentParser(description="Run the Surrender Index bot.")
        parser.add_argument('--disableTweeting', action='store_true', dest='disableTweeting')
        parser.add_argument('--disableNotifications', action='store_true', dest='disableNotifications')
        parser.add_argument('--notifyUsingTwilio', action='store_true', dest='notifyUsingTwilio')
        parser.add_argument('--debug', action='store_true', dest='debug')
        parser.add_argument('--notHeadless', action='store_true', dest='notHeadless')
        parser.add_argument('--disableFinalCheck', action='store_true', dest='disableFinalCheck')
        parser.add_argument('--enableMainAccount', action='store_true', dest='enableMainAccount')
        parser.add_argument('--disableTweepyReply', action='store_true', dest='disableTweepyReply')
        parser.add_argument('--enableCancel', action='store_true', dest='enableCancel')

        args = parser.parse_args()

        self.should_tweet = not args.disableTweeting
        self.should_text = not args.disableNotifications
        self.enable_main_account = args.enableMainAccount
        self.reply_using_tweepy = not args.disableTweepyReply
        self.enable_cancel = args.enableCancel
        self.notify_using_twilio = args.notifyUsingTwilio
        self.debug = args.debug
        self.not_headless = args.notHeadless

        print("Tweeting Enabled" if self.should_tweet else "Tweeting Disabled")
        if self.should_tweet:
            print("Main account enabled" if self.enable_main_account else "Main account disabled")
            print("Replying using tweepy" if self.reply_using_tweepy else "Replying using webdriver")

        self.historical_surrender_indices = self.load_historical_surrender_indices()
        self.sleep_time = 1
        self.completed_game_ids = set()
        self.final_games = set()

        should_continue = True
        while should_continue:
            try:
                self.session = requests.Session()
                retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
                self.session.mount('http://', HTTPAdapter(max_retries=retries))

                #self.send_heartbeat_message(should_repeat=False)
                #TODO: Add method to handle displaying status of bot
                self.update_current_week_games()
                self.load_tweeted_plays_dict()
                self.seen_plays = {}

                now = self.get_now()
                if now.hour < 5:
                    stop_date = now.replace(hour=5, minute=0, second=0, microsecond=0)
                else:
                    now += timedelta(days=1)
                    stop_date = now.replace(hour=5, minute=0, second=0, microsecond=0)

                while self.get_now() < stop_date:
                    start_time = time.time()
                    self.download_data_for_active_games()
                    self.sleep_time = 1.0
            except KeyboardInterrupt:
                should_continue = False
            except Exception as e:
                traceback.print_exc()
                print("Error occurred:", e)
                print("Sleeping for", self.sleep_time, "minutes")
                self.send_error_message(e)
                time.sleep(self.sleep_time * 60)
                self.sleep_time *= 2

if __name__ == "__main__":
    bot = SurrenderIndexBot()
    bot.run()
