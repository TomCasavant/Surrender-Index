"""
Andrew Shackelford
ashackelford@college.harvard.edu
@shackoverflow

surrender_index_bot.py
A Twitter bot that tracks every live game in the NFL,
and tweets out the "Surrender Index" of every punt
as it happens.

Inspired by SB Nation's Jon Bois @jon_bois.
"""

import json
import nflgame
import numpy as np
import scipy.stats as stats
import tweepy

# Due to limitations in nflgame, we can only get the current score of a
# game, not the score at the time of each play. Therefore, in the rare
# case of a punt return TD or muffed punt resulting in a touchdown for the
# kicking team, our score calculation will be inaccurate since the score
# when the team chose to punt will be different than the score at the end
# of the punt. Therefore, we'll need to keep track of the score of the
# previous play when calculating the Surrender Index. Since each game
# begins with at least the kickoff before a punt could occur, this dictionary
# will be updated with the necessary values before they are needed.
scores = {}

# Due to problems with the NFL api, sometimes plays will be sent down the
# wire twice if they are updated (usually to correct the line of scrimmage
# or game clock). This will cause the play to be tweeted twice, sometimes
# even three times. To fix this, we'll keep a dictionary of every play
# tweeted by every game, and ensure we don't tweet a play that's already
# been tweeted.
tweeted_plays = {}

# The authenticated Tweepy API, since it's not passed in the callback.
api = None

# Historical surrender indices, so we don't have to reload them each time.
historical_surrender_indices = None


### MISCELLANEOUS HELPER FUNCTIONS ###


def is_punt(play):
    """Determine if a play is a punt.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    bool: Whether the given play object is a punt.
    """

    try:
        return 'punts' in play.desc.lower() or 'punt is blocked' in play.desc.lower()
    except BaseException:
        return False


def get_yrdln_int(play):
    """Given a play, get the line of scrimmage as an integer.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    int: The yard line as an integer.
    """
    return int(play.data['yrdln'].split(' ')[-1])


def return_other_team(play):
    """Given a play, return the team that does not have possession.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    string: The 3-letter abbrevation of the team without possession.
    """

    if play.data['posteam'] == play.drive.game.home:
        return play.drive.game.away
    else:
        return play.drive.game.home


### CALCULATION HELPER FUNCTIONS ###


def calc_seconds_from_time_str(time_str):
    """Calculate the integer number of seconds from a time string.

    Parameters:
    time_str(string): A string in format "MM:SS" representing the game clock.

    Returns:
    int: The time string converted to an integer number of seconds.
    """

    minutes, seconds = map(int, time_str.split(":"))
    return minutes * 60 + seconds


def calc_seconds_since_halftime(play):
    """Calculate the number of seconds elapsed since halftime.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    int: The number of seconds elapsed since halftime of that play.
    """

    seconds_elapsed_in_qtr = (
        15 * 60) - calc_seconds_from_time_str(play.data['time'])
    return max(seconds_elapsed_in_qtr + (15 * 60) * (play.data['qtr'] - 3), 0)


def calc_score_diff(play):
    """Calculate the score differential of the team with possession.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    int: The score differential of the team with possession.
    """

    global scores
    if play.home:
        return scores.get(play.drive.game.home, 0) - \
            scores.get(play.drive.game.away, 0)
    else:
        return scores.get(play.drive.game.away, 0) - \
            scores.get(play.drive.game.home, 0)


### SURRENDER INDEX FUNCTIONS ###


def calc_field_pos_score(play):
    """Calculate the field position score for a play.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    float: The "field position score" for a given play,
           used to calculate the surrender index.
    """

    try:
        if '50' in play.data['yrdln']:
            return (1.1) ** 10.
        if play.data['posteam'] in play.data['yrdln']:
            return max(1., (1.1)**(get_yrdln_int(play) - 40))
        else:
            return (1.2)**(50 - get_yrdln_int(play)) * ((1.1)**(10))
    except BaseException:
        return 0.


def calc_yds_to_go_multiplier(play):
    """Calculate the yards to go multiplier for a play.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    float: The "yards to go multiplier" for a given play,
           used to calculate the surrender index.
    """

    if play.data['ydstogo'] >= 10:
        return 0.2
    elif play.data['ydstogo'] >= 7:
        return 0.4
    elif play.data['ydstogo'] >= 4:
        return 0.6
    elif play.data['ydstogo'] >= 2:
        return 0.8
    else:
        return 1.


def calc_score_multiplier(play):
    """Calculate the score multiplier for a play.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    float: The "score multiplier" for a given play,
           used to calculate the surrender index.
    """

    score_diff = calc_score_diff(play)

    if score_diff > 0:
        return 1.
    elif score_diff == 0:
        return 2.
    elif score_diff < -8.:
        return 3.
    else:
        return 4.


def calc_clock_multiplier(play):
    """Calculate the clock multiplier for a play.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    float: The "clock multiplier" for a given play,
           used to calculate the surrender index.
    """

    if calc_score_diff(play) <= 0 and play.data['qtr'] > 2:
        seconds_since_halftime = calc_seconds_since_halftime(play)
        return ((seconds_since_halftime * 0.001) ** 3.) + 1.
    else:
        return 1.


def calc_surrender_index(play):
    """Calculate the surrender index for a play.

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    float: The surrender index for a given play.
    """

    return calc_field_pos_score(play) * calc_yds_to_go_multiplier(
        play) * calc_score_multiplier(play) * calc_clock_multiplier(play)


### STRING FORMAT FUNCTIONS ###


def get_pretty_time_str(time_str):
    """Take a time string and remove a leading zero if necessary.

    Parameters:
    time_str(string): A string in format "MM:SS" representing the game clock.

    Returns:
    string: The time string with a leading zero removed, if present.
    """

    if time_str[0] == '0':
        return time_str[1:]
    else:
        return time_str

def get_qtr_str(qtr):
    """Given a quarter as an integer, return the quarter as a string.
       e.g. 1 = 1st, 2 = 2nd, 5 = OT, etc.

    Parameters:
    num(int or float): The integer you wish to convert to an ordinal string.

    Returns:
    string: The integer as an ordinal string.
    """

    if qtr < 5:
        return get_num_str(num)
    elif qtr == 5:
        return 'OT'
    elif qtr == 6:
        return '2 OT'
    elif qtr == 7:
        return '3 OT' # 3 overtimes ought to cover it
    return ''

def get_num_str(num):
    """Given a number, return the number as an ordinal string.
       e.g. 1 = 1st, 2 = 2nd, 3 = 3rd, etc.

    Parameters:
    num(int or float): The integer you wish to convert to an ordinal string.

    Returns:
    string: The integer as an ordinal string.
    """

    num = int(num)  # round down

    if num % 100 == 11 or num % 100 == 12 or num % 100 == 13:
        return str(num) + 'th'

    if num % 10 == 1:
        return str(num) + 'st'
    if num % 10 == 2:
        return str(num) + 'nd'
    if num % 10 == 3:
        return str(num) + 'rd'

    return str(num) + 'th'


def pretty_score_str(score_1, score_2):
    """Given two scores, return the scores as a pretty string.
       e.g. "winning 28 to 3"

    Parameters:
    score_1(int): The first score in the string.
    score_2(int): The second score in the string.

    Returns:
    string: The two scores as a pretty string.
    """

    if score_1 > score_2:
        ret_str = 'winning '
    elif score_2 > score_1:
        ret_str = 'losing '
    else:
        ret_str = 'tied '

    ret_str += str(score_1) + ' to ' + str(score_2)
    return ret_str


def get_score_str(play):
    """Given a play, return the game score as a pretty string,
       with the possessing team first.
       e.g. "losing 28 to 34"

    Parameters:
    play(nflgame.game.Play): The play object.

    Returns:
    string: The game score as a pretty string.
    """

    global scores
    if play.data['posteam'] == play.drive.game.home:
        return pretty_score_str(
            scores[play.drive.game.home], scores[play.drive.game.away])
    else:
        return pretty_score_str(
            scores[play.drive.game.away], scores[play.drive.game.home])


### HISTORY FUNCTIONS ###


def has_been_tweeted(play):
    """Given a play, determine if that play has been tweeted already.

    Parameters:
    play(nflgame.game.Play):

    Returns:
    bool: Whether that play has already been tweeted.
    """

    global tweeted_plays
    game_plays = tweeted_plays.get(play.drive.game.gamekey, set())
    for old_play in list(game_plays):
        if old_play.data['posteam'] == play.data['posteam'] and \
            old_play.data['qtr'] == play.data['qtr'] and \
            abs(calc_seconds_from_time_str(old_play.data['time'])
                - calc_seconds_from_time_str(play.data['time'])) < 30:
            # Check if the team with possession and quarter are the same, and
            # if the game clock at the start of the play is within 30 seconds.
            return True

    return False


def update_tweeted_plays(play):
    """Given a play, update the dictionary of already tweeted plays.

    Parameters:
    play(nflgame.game.Play): The play to put in the dictionary
                             of already tweeted plays.
    """

    global tweeted_plays
    game_plays = tweeted_plays.get(play.drive.game.gamekey, set())
    game_plays.add(play)
    tweeted_plays[play.drive.game.gamekey] = game_plays


def update_scores(game):
    """Given a game, update the scores for each team.

    Parameters:
    game(nflgame.Game): The game to update scores for.
    """

    global scores
    scores[game.home] = game.score_home
    scores[game.away] = game.score_away


### PERCENTILE FUNCTIONS ###

def load_historical_surrender_indices():
    """Load in saved surrender indices from punts from 2009 to 2018.

    Returns:
    numpy.array: A numpy array containing all loaded surrender indices.
    """

    with open('2009-2018_surrender_indices.npy', 'rb') as f:
        return np.load(f)


def load_current_surrender_indices():
    """Load in saved surrender indices from the current season's past punts.

    Returns:
    numpy.array: A numpy array containing all loaded surrender indices.
    """

    try:
        with open('current_surrender_indices.npy', 'rb') as f:
            return np.load(f)
    except BaseException:
        return np.array([])


def write_current_surrender_indices(surrender_indices):
    """Write surrender indices from the current season to file.

    Parameters:
    surrender_indices(numpy.array): The numpy array to write to file.
    """

    with open('current_surrender_indices.npy', 'wb') as f:
        np.save(f, surrender_indices)


def calculate_percentiles(surrender_index):
    """Load in past saved surrender indices, calculate the percentiles of the
       given one among current season and all since 2019, then add the given
       one to current season and write back to file.

    Parameters:
    surrender_index(float): The surrender index of a punt.

    Returns:
    float: The percentile of the given surrender index among 2019 punts.
    float: The percentile of the given surrender index among punts since 2009.
    """

    global historical_surrender_indices

    current_surrender_indices = load_current_surrender_indices()
    current_percentile = stats.percentileofscore(
        current_surrender_indices, surrender_index, kind='strict')

    all_surrender_indices = np.concatenate(
        (historical_surrender_indices, current_surrender_indices))
    historical_percentile = stats.percentileofscore(
        all_surrender_indices, surrender_index, kind='strict')

    current_surrender_indices = np.append(
        current_surrender_indices, surrender_index)
    write_current_surrender_indices(current_surrender_indices)

    return current_percentile, historical_percentile


### TWITTER FUNCTIONS ###


def initialize_api():
    """Load in the Twitter credentials and initialize the Tweepy API.

    Returns:
    tweepy.API: An instance of the Tweepy API.
    """

    with open('credentials.json', 'r') as f:
        credentials = json.load(f)
    auth = tweepy.OAuthHandler(
        credentials['consumer_key'], credentials['consumer_secret'])
    auth.set_access_token(
        credentials['access_token'], credentials['access_token_secret'])
    api = tweepy.API(auth)
    return api


def create_tweet_str(
        play,
        surrender_index,
        current_percentile,
        historical_percentile):
    """Given a play, surrender index, and two percentiles, craft a string to tweet.

    Parameters:
    play(nflgame.game.Play): The play object.
    surrender_index(float): The surrender index of the punt.
    current_percentile(float): The percentile of the surrender index in punts from the current season.
    historical_percentile(float): The percentile of the surrender index in punts since 2009.


    Returns:
    string: The string to tweet.
    """

    play_str = play.data['posteam'] + \
        ' decided to punt to ' + \
        return_other_team(play) + \
        ' from the ' + str(play.data['yrdln']) + \
        ' on ' + get_num_str(play.data['down']) + \
        ' & ' + str(play.data['ydstogo']) + \
        ' with ' + get_pretty_time_str(play.data['time']) + \
        ' remaining in the ' + get_qtr_str(play.data['qtr']) + \
        ' while ' + get_score_str(play) + '.'

    surrender_str = 'With a Surrender Index of ' + \
                    str(round(surrender_index, 2)) + \
                    ', this punt ranks at the ' + \
                    get_num_str(current_percentile) + \
                    ' percentile of cowardly punts of the 2019 season, and the ' + \
                    get_num_str(historical_percentile) + \
                    ' percentile of all punts since 2009.'

    return play_str + '\n\n' + surrender_str


def tweet_play(play):
    """Given a play, tweet it (if it hasn't already been tweeted).

    Parameters:
    play(nflgame.game.Play): The play to tweet.
    """

    global api
    if not has_been_tweeted(play):
        surrender_index = calc_surrender_index(play)
        current_percentile, historical_percentile = calculate_percentiles(
            surrender_index)
        tweet_str = create_tweet_str(
            play,
            surrender_index,
            current_percentile,
            historical_percentile)

        print(tweet_str)
        api.update_status(tweet_str)
        update_tweeted_plays(play)


### MAIN FUNCTIONS ###


def live_callback(active, completed, diffs):
    """The callback for nflgame.live.run.
       This callback is called whenever new plays are downloaded by the API.

       This callback tweets any punts contained in the diffs,
       updates the scores for each active game,
       and cleans up any tweeted punts for games that are now completed.

    Parameters:
    active(List[nflgame.game]): A list of each active game.
    completed(List[nflgame.game]): A list of each completed game.
    diffs(List[nflgame.game.GameDiff]): A list of GameDiff objects (one per
                                        game), each of which contains a list
                                        of plays that have occurred since the
                                        last update.

    Returns:
    bool: Whether that play has already been tweeted.
    """

    global tweeted_plays

    for diff in diffs:
        for play in diff.plays:
            if is_punt(play):
                tweet_play(play)

    for game in active:
        update_scores(game)

    for game in completed:
        if game.gamekey in tweeted_plays:
            del tweeted_plays[game.gamekey]


def main():
    """The main function to initialize the API and start the live callback.
    """

    global api
    global historical_surrender_indices

    api = initialize_api()
    historical_surrender_indices = load_historical_surrender_indices()
    nflgame.live.run(live_callback, active_interval=15,
                     inactive_interval=900, stop=None)


if __name__ == "__main__":
    main()