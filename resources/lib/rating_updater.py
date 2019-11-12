#!/usr/bin/python
# coding: utf-8

########################

from __future__ import division

from resources.lib.helper import *
from resources.lib.functions import *

########################

class UpdateAllRatings(object):
    def __init__(self,params):
        self.dbtype = params.get('type')
        self.background_task = ADDON.getSettingBool('update_background')

        all_items = json_call('VideoLibrary.Get%ss' % self.dbtype,
                              properties=['title', 'year']
                              )

        try:
        	self.items = all_items['result']['%ss' % self.dbtype]
        	self.total_items = len(self.items)
        	self.run()

        except Exception:
        	pass

    def run(self):
        winprop('UpdatingRatings.bool', True)
        msg_text = None

        if self.dbtype == 'movie':
            heading = ADDON.getLocalizedString(32033)
        else:
            heading = ADDON.getLocalizedString(32034)

        processed_items = 0
        progress = 0

        if self.background_task:
            progressdialog = xbmcgui.DialogProgressBG()
        else:
            progressdialog = xbmcgui.DialogProgress()

        progressdialog.create(heading, '')

        for item in self.items:
            if (not self.background_task and progressdialog.iscanceled()) or winprop('CancelRatingUpdater.bool'):
                winprop('CancelRatingUpdater', clear=True)
                msg_text = ADDON.getLocalizedString(32042)
                break

            processed_items += 1
            progress = int(100 / self.total_items * processed_items)
            label = item.get('title')

            if item.get('year'):
                label = label + ' (' + str(item.get('year')) + ')'

            if self.background_task:
                progressdialog.update(int(progress), str(processed_items) + ' / ' + str(self.total_items) + ':', label)
            else:
                progressdialog.update(int(progress), label, str(processed_items) + ' / ' + str(self.total_items))

            UpdateRating({'dbid': item.get('%sid' % self.dbtype),
                          'type': self.dbtype,
                          'done_msg': False})

        progressdialog.close()
        progressdialog = None

        notification(ADDON.getLocalizedString(32030), msg_text if msg_text else xbmc.getLocalizedString(19256))

        winprop('UpdatingRatings', clear=True)


class UpdateRating(object):
    def __init__(self,params):
        self.dbid = params.get('dbid')
        self.dbtype = params.get('type')
        self.done_msg = True if params.get('done_msg', True) else False
        self.tmdb_type = 'movie' if self.dbtype == 'movie' else 'tv'
        self.tmdb_tv_status = None
        self.tmdb_mpaa = None
        self.tmdb_mpaa_fallback = None
        self.update_uniqueid = False

        self.method_details = 'VideoLibrary.Get%sDetails' % self.dbtype
        self.method_setdetails = 'VideoLibrary.Set%sDetails' % self.dbtype
        self.param = '%sid' % self.dbtype
        self.key_details = '%sdetails' % self.dbtype

        self.init()

    def init(self):
        # get stored IDs that are used to call TMDb and OMDb
        self.get_details()

        if not self.uniqueid:
            return

        self.imdb = self.uniqueid.get('imdb')
        self.tmdb = self.uniqueid.get('tmdb')
        self.tvdb = self.uniqueid.get('tvdb')

        # get the default used rating
        self.default_rating = None
        for rating in self.ratings:
            if self.ratings[rating].get('default'):
                self.default_rating = rating
                break

        # get TMDb ID (if not available) by using the ID of IMDb or TVDb
        if not self.tmdb and self.imdb:
            self.get_tmdb_externalid(self.imdb)

        elif not self.tmdb and self.tvdb:
            self.get_tmdb_externalid(self.tvdb)

        # get TMDb rating and IMDb number if not available
        if self.tmdb:
            self.get_tmdb()

        # get Rotten, Metacritic and IMDb ratings of OMDb
        self.get_omdb()

        # update db + nfo
        self.update_info()

        if self.done_msg:
            notification(ADDON.getLocalizedString(32030), xbmc.getLocalizedString(19256))

    def get_details(self):
        json_query = json_call(self.method_details,
                               properties=['title', 'originaltitle', 'year', 'uniqueid', 'ratings', 'file', 'tag'],
                               params={self.param: int(self.dbid)}
                               )
        try:
            result = json_query['result'][self.key_details]
        except KeyError:
            result = {}

        self.uniqueid = result.get('uniqueid', {})
        self.ratings = result.get('ratings', {})
        self.file = result.get('file')
        self.year = result.get('year')
        self.title = result.get('title')
        self.original_title = result.get('originaltitle') or self.title
        self.tags = result.get('tag')

    def get_tmdb(self):
        country_code = ADDON.getSetting('country_code')

        result = tmdb_call(action=self.tmdb_type,
                           call=str(self.tmdb),
                           params={'append_to_response': 'release_dates,content_ratings,external_ids'}
                           )

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
            self._update_ratings_dict(key='themoviedb', rating=self.tmdb_rating, votes=self.tmdb_votes)

        # set MPAA based on setting
        if not ADDON.getSettingBool('skip_mpaa'):
            if self.tmdb_type == 'movie':
                release_dates = result['release_dates']['results']

                for country in release_dates:
                    if country.get('iso_3166_1') == country_code:
                        self.tmdb_mpaa = country['release_dates'][0].get('certification')
                        break

                    elif country.get('iso_3166_1') == 'US':
                        self.tmdb_mpaa_fallback = country['release_dates'][0].get('certification')

            if self.tmdb_type == 'tv':
                content_ratings = result['content_ratings']['results']

                for country in content_ratings:
                    if country.get('iso_3166_1') == country_code:
                        self.tmdb_mpaa = country.get('rating')
                        break

                    elif country.get('iso_3166_1') == 'US':
                        self.tmdb_mpaa_fallback = country.get('rating')

            if self.tmdb_mpaa:
                if country_code == 'DE':
                    self.tmdb_mpaa = 'FSK ' + self.tmdb_mpaa

                self._set_value('mpaa', self.tmdb_mpaa)

            elif self.tmdb_mpaa_fallback:
                self._set_value('mpaa', self.tmdb_mpaa_fallback)

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
        result = tmdb_call(action='find',
                           call=str(external_id),
                           params={'external_source': 'imdb_id' if external_id.startswith('tt') else 'tvdb_id'}
                           )

        try:
            if self.dbtype == 'movie':
                self.tmdb = result['movie_results'][0].get('id')

            elif self.dbtype == 'tvshow':
                self.tmdb = result['tv_results'][0].get('id')

            if self.tmdb:
                self._update_uniqueid_dict('tmdb', self.tmdb)

        except Exception:
            pass

    def get_omdb(self):
        omdb = omdb_call(imdbnumber=self.imdb,
                         title=self.original_title,
                         year=self.year)

        if not omdb:
            return

        tree = ET.ElementTree(ET.fromstring(omdb))
        root = tree.getroot()

        for child in root:
            # imdb ratings
            imdb_rating = child.get('imdbRating')
            imdb_votes = child.get('imdbVotes', 0)

            if imdb_rating and imdb_rating != 'N/A':
                votes = imdb_votes.replace(',', '') if imdb_votes != 'N/A' else 0
                self._update_ratings_dict(key='imdb',
                                          rating=float(imdb_rating),
                                          votes=int(votes)
                                          )

                # Emby For Kodi is storing the rating as 'default'
                if 'default' in self.ratings:
                    self._update_ratings_dict(key='default',
                                              rating=float(imdb_rating),
                                              votes=int(votes)
                                              )

            # regular rotten rating
            tomatometerallcritics = child.get('tomatoMeter')
            tomatometerallcritics_votes = child.get('tomatoReviews', 0)

            if tomatometerallcritics and tomatometerallcritics != 'N/A':
                tomatometerallcritics = int(tomatometerallcritics) / 10
                votes = tomatometerallcritics_votes if tomatometerallcritics_votes != 'N/A' else 0
                self._update_ratings_dict(key='tomatometerallcritics',
                                          rating=tomatometerallcritics,
                                          votes=int(votes))

            # user rotten rating
            tomatometeravgcritics = child.get('tomatoUserMeter')
            tomatometeravgcritics_votes = child.get('tomatoUserReviews', 0)

            if tomatometeravgcritics and tomatometeravgcritics != 'N/A':
                tomatometeravgcritics = int(tomatometeravgcritics) / 10
                votes = tomatometeravgcritics_votes if tomatometeravgcritics_votes != 'N/A' else 0
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

            # TMDb doesn't store IMDb numbers for shows so store the one found via OMDb
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

        # nfo updating
        if self.file:
            elems = ['ratings', 'uniqueid']
            values = [self.ratings, [self.uniqueid, None]]

            # TV status
            if self.tmdb_tv_status:
                elems.append('status')
                values.append(self.tmdb_tv_status)

            # MPAA
            if self.tmdb_mpaa:
                elems.append('mpaa')
                values.append(self.tmdb_mpaa)

            elif self.tmdb_mpaa_fallback:
                elems.append('mpaa')
                values.append(self.tmdb_mpaa_fallback)

            # Write tags to nfo in case they weren't there to trigger Emby to add them
            if self.tags:
                elems.append('tag')
                values.append(self.tags)

            update_nfo(file=self.file,
                       elem=elems,
                       value=values,
                       dbtype=self.dbtype,
                       dbid=self.dbid)

    def _update_ratings_dict(self,key,rating,votes):
        self.ratings[key] = {'default': True if key == self.default_rating else False,
                             'rating': rating,
                             'votes': votes}

    def _update_uniqueid_dict(self,key,value):
        self.uniqueid[key] = str(value)
        self.update_uniqueid = True

    def _set_value(self,key,value):
        json_call('VideoLibrary.Set%sDetails' % self.dbtype,
                  params={key: value, '%sid' % self.dbtype: int(self.dbid)},
                  debug=LOG_JSON
                  )