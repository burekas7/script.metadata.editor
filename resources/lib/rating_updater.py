#!/usr/bin/python
# coding: utf-8

########################

from __future__ import division

from resources.lib.helper import *
from resources.lib.functions import *
from resources.lib.database import *
from resources.lib.nfo_updater import *

########################

RUN_IN_BACKGROUND = ADDON.getSettingBool('update_background')
OMDB_FALLBACK = ADDON.getSettingBool('omdb_fallback_search')
OMDB_API = ADDON.getSetting('omdb_api_key')
COUNTRY_CODE = ADDON.getSetting('country_code')
SKIP_MPAA = ADDON.getSettingBool('mpaa_skip')
SKIP_NOT_RATED = ADDON.getSettingBool('mpaa_skip_nr')
MPAA_FALLBACK = ADDON.getSettingBool('mpaa_fallback')
TMDB_LANGUAGE = ADDON.getSetting('tmdb_language')

########################

def update_ratings(dbid=None,dbtype=None,content=None):
    # no omdb API key message
    if not OMDB_API:
        if not DIALOG.yesno(xbmc.getLocalizedString(14117), ADDON.getLocalizedString(32035)):
            return

    winprop('UpdatingRatings.bool', True)
    msg_text = xbmc.getLocalizedString(19256)

    # get database ids
    if isinstance(dbtype, str):
        dbtype = dbtype.split('+')

    db = Database(dbid=dbid, append=['episodes'])
    for i in dbtype:
        getattr(db, i)()
    result = db.result()

    # calc total items to process
    total_items = 0
    for i in result:
        if result.get(i):
            total_items = total_items + len(result[i])

    if total_items > 1:
        # show progress if 1< will be processed
        progressdialog = ProgressDialog(total_items)

        for i in result:
            if i == 'movie':
                cat = xbmc.getLocalizedString(20338)
            elif i == 'tvshow':
                cat = xbmc.getLocalizedString(20364)
            elif i == 'episode':
                cat = xbmc.getLocalizedString(20359)

            for item in result[i]:
                if progressdialog.canceled():
                    break

                if item.get('showtitle') and item.get('label'):
                    label = item.get('showtitle') + ' - ' + item.get('label')
                else:
                    label = item.get('title')

                if item.get('year'):
                    label = label + ' (' + str(item.get('year')) + ')'

                progressdialog.update(cat, label)

                UpdateRating({'dbid': item.get('%sid' % i),
                              'type': i})

            if progressdialog.canceled():
                msg_text = ADDON.getLocalizedString(32042)
                break

        progressdialog.close()

    elif total_items == 1:
        # process single item
        for i in result:
            UpdateRating({'dbid': result[i][0].get('%sid' % i),
                          'type': i})

    else:
        # error message
        msg_text = ADDON.getLocalizedString(32048)

    winprop('UpdatingRatings', clear=True)
    notification(ADDON.getLocalizedString(32030), msg_text)


class ProgressDialog(object):
    def __init__(self,total_items):
        if RUN_IN_BACKGROUND:
            self.progressdialog = xbmcgui.DialogProgressBG()
        else:
            self.progressdialog = xbmcgui.DialogProgress()

        self.progressdialog.create('Updating', '')
        self.total_items = total_items
        self.processed_items = 0
        self.progress = 0

    def canceled(self):
        if RUN_IN_BACKGROUND:
            return True if winprop('CancelRatingUpdater.bool') else False
        else:
            return True if self.progressdialog.iscanceled() or winprop('CancelRatingUpdater.bool') else False

    def update(self,cat,label):
        self.processed_items += 1
        progress = int(100 / self.total_items * self.processed_items)
        processed = str(self.processed_items) + ' / ' + str(self.total_items)

        if RUN_IN_BACKGROUND:
            self.progressdialog.update(progress, processed, cat + ':' + label)
        else:
            self.progressdialog.update(progress, cat + ':[CR]' + label, processed)

    def close(self):
        self.progressdialog.close()
        self.progressdialog = None
        winprop('CancelRatingUpdater', clear=True)


class UpdateRating(object):
    def __init__(self,params):
        self.dbid = params.get('dbid')
        self.dbtype = params.get('type')
        self.tmdb_type = 'movie' if self.dbtype == 'movie' else 'tv'
        self.tmdb_tv_status = None
        self.tmdb_mpaa = None
        self.tmdb_mpaa_fallback = None
        self.tmdb_rating = None
        self.imdb_rating = None
        self.omdb_limit = False
        self.update_uniqueid = False
        self.episodeguide = None

        # collect db data
        self.db = Database(dbid=self.dbid, dbtype=self.dbtype)
        self.get_details()

        self.uniqueid = self.details.get('uniqueid', {})
        self.ratings = self.details.get('ratings', {})
        self.file = self.details.get('file')
        self.year = self.details.get('year')
        self.title = self.details.get('title')
        self.original_title = self.details.get('originaltitle') or self.title
        self.tags = self.details.get('tag')

        if ('thetvdb' or 'themoviedb') in self.details.get('episodeguide', ''):
            self.episodeguide = self.details.get('episodeguide')
        else:
            self.episodeguide = None

        if self.uniqueid:
            self.run()

    def get_details(self):
        getattr(self.db, self.dbtype)()
        self.details = self.db.result().get(self.dbtype)[0]

    def run(self):
        self.imdb = self.uniqueid.get('imdb')
        self.tmdb = self.uniqueid.get('tmdb')
        self.tvdb = self.uniqueid.get('tvdb')

        # don't proceed for episodes if no IMDb is available
        if self.dbtype == 'episode' and not self.imdb:
            return

        # get the default used rating
        self.default_rating = None
        for rating in self.ratings:
            if self.ratings[rating].get('default'):
                self.default_rating = rating
                break

        if self.dbtype != 'episode':
            # get TMDb ID (if not available) by using the ID of IMDb or TVDb
            if not self.tmdb and self.imdb:
                self.get_tmdb_externalid(self.imdb)

            elif not self.tmdb and self.tvdb:
                self.get_tmdb_externalid(self.tvdb)

            # get TMDb rating and IMDb number if not available
            if self.tmdb:
                self.get_tmdb()

        # get Rotten, Metacritic and IMDb ratings of OMDb
        if not self.omdb_limit:
            self.get_omdb()

        # if no TMDb ID was known before but OMDb return the IMDb ID -> try to get TMDb data again
        if self.dbtype != 'episode' and not self.tmdb and self.imdb:
            self.get_tmdb_externalid(self.imdb)

            if self.tmdb:
                self.get_tmdb()

        # emby <ratings> and <votes>
        if 'default' in self.ratings:
            self.emby_ratings()

        # update db + nfo
        self.update_info()

    def emby_ratings(self):
        # Emby For Kodi is storing the rating as 'default'
        if self.imdb_rating:
            self._update_ratings_dict(key='default',
                                      rating=float(self.imdb_rating),
                                      votes=int(self.imdb_votes)
                                      )

        elif self.tmdb_rating:
            self._update_ratings_dict(key='default',
                                      rating=float(self.tmdb_rating),
                                      votes=int(self.tmdb_votes)
                                      )

    def get_tmdb(self):
        result = self._tmdb(action=self.tmdb_type,
                            call=str(self.tmdb),
                            params={'append_to_response': 'release_dates,content_ratings,external_ids'}
                            )

        if not result:
            return

        self.tmdb_rating = result.get('vote_average')
        self.tmdb_votes = result.get('vote_count')
        self.original_title = result.get('original_name')

        if self.tmdb_type == 'tv':
            year = result.get('first_air_date')
            self.tmdb_tv_status = result.get('status')

            # update TV status as well
            if self.tmdb_tv_status:
                self._set_value('status', self.tmdb_tv_status)

        else:
            year = result.get('release_date')

        self.year = year[:4] if year else ''

        if self.tmdb_rating:
            self._update_ratings_dict(key='themoviedb',
                                      rating=self.tmdb_rating,
                                      votes=self.tmdb_votes
                                      )

        # set MPAA based on setting
        if not SKIP_MPAA:
            if self.tmdb_type == 'movie':
                release_dates = result['release_dates']['results']

                for country in release_dates:
                    if country.get('iso_3166_1') == COUNTRY_CODE:
                        for item in country['release_dates']:
                            if item.get('certification'):
                                self.tmdb_mpaa = item.get('certification')
                                break
                        break

                    elif country.get('iso_3166_1') == 'US':
                        for item in country['release_dates']:
                            if item.get('certification'):
                                self.tmdb_mpaa = item.get('certification')
                                break

            if self.tmdb_type == 'tv':
                content_ratings = result['content_ratings']['results']

                for country in content_ratings:
                    if country.get('iso_3166_1') == COUNTRY_CODE:
                        self.tmdb_mpaa = country.get('rating')
                        break

                    elif country.get('iso_3166_1') == 'US':
                        self.tmdb_mpaa_fallback = country.get('rating')

            if SKIP_NOT_RATED:
                if self.tmdb_mpaa == 'NR':
                    self.tmdb_mpaa = None

                if self.tmdb_mpaa_fallback == 'NR':
                    self.tmdb_mpaa_fallback = None

            if self.tmdb_mpaa:
                if COUNTRY_CODE == 'DE':
                    self.tmdb_mpaa = 'FSK ' + self.tmdb_mpaa

                self._set_value('mpaa', self.tmdb_mpaa)

            elif self.tmdb_mpaa_fallback and MPAA_FALLBACK:
                self._set_value('mpaa', self.tmdb_mpaa_fallback)

            else:
                self._set_value('mpaa', '')

        # set IMDb ID if not available in the library
        if not self.imdb:
            if self.tmdb_type == 'movie':
                self.imdb = result.get('imdb_id')

            elif self.tmdb_type == 'tv':
                self.imdb = result['external_ids'].get('imdb_id')

            if self.imdb:
                self._update_uniqueid_dict('imdb', self.imdb)

        # add TVDb ID to uniqueid if missing
        if not self.tvdb and self.tmdb_type == 'tv':
            self.tvdb = result['external_ids'].get('tvdb_id')

            if self.tvdb:
                self._update_uniqueid_dict('tvdb', self.tvdb)

    def get_tmdb_externalid(self,external_id):
        result = self._tmdb(action='find',
                            call=str(external_id),
                            params={'external_source': 'imdb_id' if external_id.startswith('tt') else 'tvdb_id'}
                            )

        if self.dbtype == 'movie' and result.get('movie_results'):
            self.tmdb = result['movie_results'][0].get('id')

        elif self.dbtype == 'tvshow' and result.get('tv_results'):
            self.tmdb = result['tv_results'][0].get('id')

        if self.tmdb:
            self._update_uniqueid_dict('tmdb', self.tmdb)

    def get_omdb(self):
        omdb = self._omdb()

        if not omdb:
            return

        tree = ET.ElementTree(ET.fromstring(omdb))
        root = tree.getroot()

        for child in root:
            # imdb ratings
            imdb_rating = child.get('imdbRating', '')
            imdb_votes = child.get('imdbVotes', '0')

            self.imdb_rating = imdb_rating.replace(',', '') if imdb_rating != 'N/A' else ''
            self.imdb_votes = imdb_votes.replace(',', '') if imdb_votes != 'N/A' else 0

            if self.imdb_rating:
                self._update_ratings_dict(key='imdb',
                                          rating=float(self.imdb_rating),
                                          votes=int(self.imdb_votes)
                                          )

            # regular rotten rating
            tomatometerallcritics = child.get('tomatoMeter')
            tomatometerallcritics_votes = child.get('tomatoReviews', '0')

            if tomatometerallcritics and tomatometerallcritics != 'N/A':
                tomatometerallcritics = int(tomatometerallcritics) / 10
                votes = tomatometerallcritics_votes.replace(',', '') if tomatometerallcritics_votes != 'N/A' else 0
                self._update_ratings_dict(key='tomatometerallcritics',
                                          rating=tomatometerallcritics,
                                          votes=int(votes))

            # user rotten rating
            tomatometeravgcritics = child.get('tomatoUserMeter')
            tomatometeravgcritics_votes = child.get('tomatoUserReviews', '0')

            if tomatometeravgcritics and tomatometeravgcritics != 'N/A':
                tomatometeravgcritics = int(tomatometeravgcritics) / 10
                votes = tomatometeravgcritics_votes.replace(',', '') if tomatometeravgcritics_votes != 'N/A' else 0
                self._update_ratings_dict(key='tomatometeravgcritics',
                                          rating=tomatometeravgcritics,
                                          votes=int(votes))

            # metacritic
            metacritic = child.get('metascore')

            if metacritic and metacritic != 'N/A':
                metacritic = int(metacritic) / 10
                self._update_ratings_dict(key='metacritic',
                                          rating=metacritic,
                                          votes=0)

            # set imdb if not set before
            if not self.imdb and child.get('imdbID') and child.get('imdbID') != 'N/A':
                self.imdb = child.get('imdbID')
                self._update_uniqueid_dict('imdb', child.get('imdbID'))

            break

    def update_info(self):
        # set at least one default rating if none is set in the library
        if not self.default_rating and self.ratings:
            for item in ['imdb', 'themoviedb', 'tomatometerallcritics', 'tomatometeravgcritics', 'metacritic']:
                if item in self.ratings:
                    self.default_rating = item
                    break

            # unkown rating source is stored -> use the first one
            if not self.default_rating:
                for item in self.ratings:
                    self.default_rating = item
                    break

        # update to library
        json_call('VideoLibrary.Set%sDetails' % self.dbtype,
                  params={'ratings': self.ratings, '%sid' % self.dbtype: int(self.dbid)},
                  debug=LOG_JSON
                  )

        if self.update_uniqueid:
            json_call('VideoLibrary.Set%sDetails' % self.dbtype,
                      params={'uniqueid': self.uniqueid, '%sid' % self.dbtype: int(self.dbid)},
                      debug=LOG_JSON
                      )

        # episode guide verification
        if self.episodeguide:
            if 'thetvdb' in self.episodeguide and 'tvdb' not in self.uniqueid:
                self.episodeguide = None
            elif 'themoviedb' in self.episodeguide and 'tmdb' not in self.uniqueid:
                self.episodeguide = None

        if self.dbtype == 'tvshow' and not self.episodeguide:
            if 'tvdb' in self.uniqueid:
                value = self.uniqueid.get('tvdb')
                url = 'https://api.thetvdb.com/login?{"apikey":"439DFEBA9D3059C6","id":%s}|Content-Type=application/json' % str(value)
                json_value = '<episodeguide><url post="yes" cache="auth.json"><url>%s</url></episodeguide>' % url

            elif 'tmdb' in self.uniqueid:
                value = self.uniqueid.get('tmdb')
                cache = 'tmdb-%s-%s.json' % (str(value), TMDB_LANGUAGE)
                url = 'http://api.themoviedb.org/3/tv/%s?api_key=6a5be4999abf74eba1f9a8311294c267&amp;language=%s' % (str(value), TMDB_LANGUAGE)
                json_value = '<episodeguide><url cache="%s"><url>%s</url></episodeguide>' % (cache, url)

            else:
                json_value = '<episodeguide><url cache=""><url></url></episodeguide>'

            self.episodeguide = json_value
            self._set_value('episodeguide', json_value)

        # nfo updating
        if self.file:
            # get updated data
            self.get_details()

            # TV status cannot be fetched in Leia
            if self.tmdb_tv_status and not self.details.get('status'):
                self.details['status'] = self.tmdb_tv_status

            update_nfo(file=self.file,
                       dbtype=self.dbtype,
                       dbid=self.dbid,
                       details=self.details
                       )

    def _update_ratings_dict(self,key,rating,votes):
        self.ratings[key] = {'default': True if key == self.default_rating else False,
                             'rating': rating,
                             'votes': votes}

    def _update_uniqueid_dict(self,key,value):
        self.uniqueid[key] = str(value)
        self.update_uniqueid = True

    def _set_value(self,key,value):
        self.db.set(key=key, value=value)

    def _omdb(self):
        if self.imdb:
            url = 'http://www.omdbapi.com/?apikey=%s&i=%s&plot=short&r=xml&tomatoes=true' % (OMDB_API, self.imdb)

        elif OMDB_FALLBACK and self.dbtype != 'episode' and title and year:
            # urllib has issues with some asian letters
            try:
                title = urllib.quote(title)
            except KeyError:
                return

            url = 'http://www.omdbapi.com/?apikey=%s&t=%s&year=%s&plot=short&r=xml&tomatoes=true' % (OMDB_API, title, year)

        else:
            return

        for i in range(1,10): # loop if heavy server load
            request = requests.get(url)
            if not str(request.status_code).startswith('5'):
                break
            xbmc.sleep(500)

        if request.status_code == 401:
            if DIALOG.yesno(xbmc.getLocalizedString(257), 'OMDB API limit reached. Please consider to become a Patreon to increase your daily call limitation. Proceed by only using The Movie DB?'):
                self.omdb_limit = True
            else:
                winprop('CancelRatingUpdater.bool', True)
            return

        if request.status_code != requests.codes.ok:
            return

        result = request.content

        if not result or '<root response="False">' in result:
            error_msg = 'OMDb error for "%s" IMDBd "%s" --> ' % (self.original_title, self.imdb)
            log(error_msg + str(omdb), WARNING)
            return

        return result

    def _tmdb(self,action,call=None,get=None,params=None):
        args = {}
        args['api_key'] = 'fc168650632c6597038cf7072a7c20da'

        if params:
            args.update(params)

        call = '/' + str(call) if call else ''
        get = '/' + get if get else ''

        url = 'https://api.themoviedb.org/3/' + action + call + get
        url = '{0}?{1}'.format(url, urlencode(args))

        for i in range(1,10): # loop if heavy server load
            request = requests.get(url)
            if not str(request.status_code).startswith('5'):
                break
            xbmc.sleep(500)

        result = {}
        if request.status_code == requests.codes.ok:
            result = request.json()

        return result