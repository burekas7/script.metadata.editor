#!/usr/bin/python

########################

from resources.lib.helper import *
from resources.lib.editor import *
from resources.lib.rating_updater import *

########################

class Main:
    def __init__(self):
        self._parse_argv()
        self.dbid = self.params.get('dbid')
        self.dbtype = self.params.get('type')

        if self.action == 'updaterating' or not self.params:
            if winprop('UpdatingRatings.bool'):
                if DIALOG.yesno(xbmc.getLocalizedString(14117), ADDON.getLocalizedString(32050)):
                    winprop('CancelRatingUpdater.bool', True)
                return

            menu_items = [ADDON.getLocalizedString(32038), ADDON.getLocalizedString(32037), ADDON.getLocalizedString(32036), ADDON.getLocalizedString(32045)]
            menu_actions = [['movies', 'tvshows', 'episodes'], 'movies', 'tvshows', 'episodes']

            if self.action:
                if self.dbid and self.dbtype in ['movie', 'tvshow', 'episode']:
                    update_ratings(dbid=self.dbid, dbtype=self.dbtype)

                elif not self.dbtype:
                    update_ratings(dbtype=menu_actions[0])

                elif self.dbtype in menu_actions:
                    update_ratings(dbtype=menu_actions[menu_actions.index(self.dbtype)])

                else:
                    DIALOG.ok(xbmc.getLocalizedString(257), ADDON.getLocalizedString(32049) + '.[CR]ID: ' + str(self.dbid) +  ' - ' + ADDON.getLocalizedString(32051) + ': ' + str(self.dbtype))

            else:
                updateselector = DIALOG.contextmenu(menu_items)
                if updateselector >= 0:
                    update_ratings(dbtype=menu_actions[updateselector])

        elif self.action == 'togglewatchlist':
            self._set(key='tag', valuetype='watchlist')

        elif self.action == 'setgenre':
            self._set(key='genre', valuetype='select')

        elif self.action == 'settags':
            self._set(key='tag', valuetype='select')

        elif self.action == 'setuserrating':
            self._set(key='userrating', valuetype='userrating')

        else:
            self._editor()

    def _parse_argv(self):
        args = sys.argv

        for arg in args:
            if arg == ADDON_ID:
                continue

            if arg.startswith('action='):
                self.action = arg[7:].lower()
            else:
                self.action = None
                try:
                    self.params[arg.split("=")[0].lower()] = "=".join(arg.split("=")[1:]).strip()
                except:
                    self.params = {}

    def _set(self,key,valuetype):
        editor = EditDialog(dbid=self.dbid, dbtype=self.dbtype)
        editor.set(key=key, type=valuetype)

    def _editor(self):
        editor = EditDialog(dbid=self.dbid, dbtype=self.dbtype)
        editor.editor()


if __name__ == '__main__':
    Main()
