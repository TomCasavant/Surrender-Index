def time_print(message):
    print(message)

# Dictionary of teams (reversed for easier lookup by ID)
teams = { 
    '22': 'ARI', '1': 'ATL', '33': 'BAL', '2': 'BUF', '29': 'CAR',
    '3': 'CHI', '4': 'CIN', '5': 'CLE', '6': 'DAL', '7': 'DEN',
    '8': 'DET', '9': 'GB', '34': 'HOU', '11': 'IND', '30': 'JAX',
    '12': 'KC', '13': 'LV', '24': 'LAC', '14': 'LAR', '15': 'MIA',
    '16': 'MIN', '17': 'NE', '18': 'NO', '19': 'NYG', '20': 'NYJ',
    '21': 'PHI', '23': 'PIT', '25': 'SF', '26': 'SEA', '27': 'TB',
    '10': 'TEN', '28': 'WSH'
}

class SurrenderIndex:

    @staticmethod
    def is_in_opposing_territory(play):
        team_id = str(play['start']['team']['id'])
        
        team_abbreviation = teams.get(team_id) # -> MIA
        
        possession_text = play['start']['possessionText'] # e.g. MIA 34
        
        if team_abbreviation and team_abbreviation in possession_text:
            # Team is on their own side
            return False
        else:
            # Team is on the opposing side
            return True

    @staticmethod
    def is_in_opposing_territory_original(play):
        print(play['start'])
        print(play['start']['yardsToEndzone'])
        return play['start']['yardsToEndzone'] < 50

    def get_debug_str(play):
        opposing = "In Opponents Territory: " + str(SurrenderIndex.is_in_opposing_territory(play))
        yards = "Yards to Endzone: " + str(play['start']['yardsToEndzone'])
        yardline = "Current Yardline: " + str(play['start']['yardLine'])
        return "\nDebug:\n" + opposing + "\n" + yards + "\n" + yardline
    
    @staticmethod
    def get_yrdln_int(play):
        if play['start']['yardLine'] == 50:
            return 50
        return int(play['start']['possessionText'].split(' ')[1])
    
    @staticmethod
    def get_qtr_num(play):
        return play['period']['number']


    @staticmethod
    def calc_score_diff(play, drive, game, debug=False):
        away, home = play['awayScore'], play['homeScore']
        if SurrenderIndex.get_possessing_team(play, game) == SurrenderIndex.get_home_team(game):
            score_diff = home - away
        else:
            score_diff = away - home
        if debug:
            time_print(("score diff", score_diff))
        return score_diff

    @staticmethod
    def get_possessing_team(play, game):
        team_id = play.get('start', {}).get('team', {}).get('id')
        if not team_id:
            team_id = play.get('end', {}).get('team', {}).get('id')
        for team in game.game_summary['boxscore']['teams']:
            if team['team']['id'] == team_id:
                return team['team']['abbreviation']
    
    @staticmethod
    def get_home_team(game):
        return game.game_summary['boxscore']['teams'][1]['team']['abbreviation']


    @staticmethod
    def calc_field_pos_score(play):
        try:
            print("IS IN OPPOSING TERRITORY?")
            time_print(SurrenderIndex.is_in_opposing_territory(play))
            if play['start']['yardLine'] == 50:
                return (1.1)**10.
            if not SurrenderIndex.is_in_opposing_territory(play):
                return max(1., (1.1)**(SurrenderIndex.get_yrdln_int(play) - 40))
            else:
                return (1.2)**(50 - SurrenderIndex.get_yrdln_int(play)) * ((1.1)**(10))
        except BaseException:
            return 0.

    @staticmethod
    def get_dist_num(play):
        return play['start']['distance']

    @staticmethod
    def calc_yds_to_go_multiplier(play):
        dist = SurrenderIndex.get_dist_num(play)
        if dist >= 10:
            return 0.2
        elif dist >= 7:
            return 0.4
        elif dist >= 4:
            return 0.6
        elif dist >= 2:
            return 0.8
        else:
            return 1.

    @staticmethod
    def calc_score_multiplier(prev_play, drive, game):
        score_diff = SurrenderIndex.calc_score_diff(prev_play, drive, game)
        if score_diff > 0:
            return 1.
        elif score_diff == 0:
            return 2.
        elif score_diff < -8.:
            return 3.
        else:
            return 4.

    @staticmethod
    def calc_seconds_from_time_str(time_str):
        minutes, seconds = map(int, time_str.split(":"))
        return minutes * 60 + seconds

    @staticmethod
    def calc_clock_multiplier(play, prev_play, drive, game):
        if SurrenderIndex.calc_score_diff(prev_play, drive, game) <= 0 and SurrenderIndex.get_qtr_num(play) > 2:
            seconds_since_halftime = SurrenderIndex.calc_seconds_since_halftime(play, game)
            return ((seconds_since_halftime * 0.001)**3.) + 1.
        else:
            return 1.
    
    @staticmethod
    def get_time_str(play):
        return play['clock']['displayValue']
    
    @staticmethod
    def calc_seconds_since_halftime(play, game, debug=True):
        # Regular season games have only one overtime of length 10 minutes
        if not game.is_postseason and SurrenderIndex.get_qtr_num(play) == 5:
            seconds_elapsed_in_qtr = (10 * 60) - SurrenderIndex.calc_seconds_from_time_str(
                SurrenderIndex.get_time_str(play))
        else:
            seconds_elapsed_in_qtr = (15 * 60) - SurrenderIndex.calc_seconds_from_time_str(
                SurrenderIndex.get_time_str(play))
        seconds_since_halftime = max(
            seconds_elapsed_in_qtr + (15 * 60) * (SurrenderIndex.get_qtr_num(play) - 3), 0)
        if debug:
            time_print(("seconds since halftime", seconds_since_halftime))
        return seconds_since_halftime

    @classmethod
    def calc_surrender_index(self, play, prev_play, drive, game, debug=True):
        field_pos_score = SurrenderIndex.calc_field_pos_score(play)
        yds_to_go_mult = SurrenderIndex.calc_yds_to_go_multiplier(play)
        score_mult = SurrenderIndex.calc_score_multiplier(prev_play, drive, game)
        clock_mult = SurrenderIndex.calc_clock_multiplier(play, prev_play, drive, game)
        #TODO: Formalize Debug setting
        if debug:
            time_print(play)
            time_print("")
            time_print(("field pos score", field_pos_score))
            time_print(("yds to go mult", yds_to_go_mult))
            time_print(("score mult", score_mult))
            time_print(("clock mult", clock_mult))
        return field_pos_score * yds_to_go_mult * score_mult * clock_mult
