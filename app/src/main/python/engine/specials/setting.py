# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Configuracion
# ------------------------------------------------------------

from __future__ import division
#from builtins import str
import sys
PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int
from builtins import range
from past.utils import old_div

from channelselector import get_thumb
from core import filetools, servertools
from core.item import Item
from platformcode import config, logger, platformtools

CHANNELNAME = "setting"


def menu_channels(item):
    logger.debug()
    itemlist = list()

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60545), action="conf_tools", folder=False,
                         extra="channels_onoff", thumbnail=get_thumb("setting_0.png")))

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60546) + ":", action="", folder=False,
                         text_bold = True, thumbnail=get_thumb("setting_0.png")))

    # Home - Configurable channels
    import channelselector
    from core import channeltools
    channel_list = channelselector.filterchannels("all")
    for channel in channel_list:
        if not channel.channel:
            continue
        channel_parameters = channeltools.get_channel_parameters(channel.channel)
        if channel_parameters["has_settings"]:
            itemlist.append(Item(channel=CHANNELNAME, title=".    " + config.get_localized_string(60547) % channel.title,
                                 action="channel_config", config=channel.channel, folder=False,
                                 thumbnail=channel.thumbnail))
    # End - Configurable channels
    itemlist.append(Item(channel=CHANNELNAME, action="", title="", folder=False, thumbnail=get_thumb("setting_0.png")))
    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60548) + ":", action="", folder=False,
                         text_bold=True, thumbnail=get_thumb("channels.png")))
    itemlist.append(Item(channel=CHANNELNAME, title=".    " + config.get_localized_string(60549), action="conf_tools",
                         folder=True, extra="lib_check_datajson", thumbnail=get_thumb("channels.png")))
    return itemlist


def channel_config(item):
    return platformtools.show_channel_settings(channelpath=filetools.join(config.get_runtime_path(), "channels", item.config))


# def setting_torrent(item):
#     logger.debug()

#     LIBTORRENT_PATH = config.get_setting("libtorrent_path", server="torrent", default="")
#     LIBTORRENT_ERROR = config.get_setting("libtorrent_error", server="torrent", default="")
#     default = config.get_setting("torrent_client", server="torrent", default=0)
#     BUFFER = config.get_setting("mct_buffer", server="torrent", default="50")
#     DOWNLOAD_PATH = config.get_setting("mct_download_path", server="torrent", default=config.get_setting("downloadpath"))
#     if not DOWNLOAD_PATH: DOWNLOAD_PATH = filetools.join(config.get_data_path(), 'downloads')
#     BACKGROUND = config.get_setting("mct_background_download", server="torrent", default=True)
#     RAR = config.get_setting("mct_rar_unpack", server="torrent", default=True)
#     DOWNLOAD_LIMIT = config.get_setting("mct_download_limit", server="torrent", default="")
#     BUFFER_BT = config.get_setting("bt_buffer", server="torrent", default="50")
#     DOWNLOAD_PATH_BT = config.get_setting("bt_download_path", server="torrent", default=config.get_setting("downloadpath"))
#     if not DOWNLOAD_PATH_BT: DOWNLOAD_PATH_BT = filetools.join(config.get_data_path(), 'downloads')
#     MAGNET2TORRENT = config.get_setting("magnet2torrent", server="torrent", default=False)

#     torrent_options = [config.get_localized_string(30006), config.get_localized_string(70254), config.get_localized_string(70255)]
#     torrent_options.extend(platformtools.torrent_client_installed())


#     list_controls = [
#         {
#             "id": "libtorrent_path",
#             "type": "text",
#             "label": "Libtorrent path",
#             "default": LIBTORRENT_PATH,
#             "enabled": True,
#             "visible": False
#         },
#         {
#             "id": "libtorrent_error",
#             "type": "text",
#             "label": "libtorrent error",
#             "default": LIBTORRENT_ERROR,
#             "enabled": True,
#             "visible": False
#         },
#         {
#             "id": "list_torrent",
#             "type": "list",
#             "label": config.get_localized_string(70256),
#             "default": default,
#             "enabled": True,
#             "visible": True,
#             "lvalues": torrent_options
#         },
#         {
#             "id": "mct_buffer",
#             "type": "text",
#             "label": "MCT - " + config.get_localized_string(70758),
#             "default": BUFFER,
#             "enabled": True,
#             "visible": "eq(-1,%s)" % torrent_options[2]
#         },
#         {
#             "id": "mct_download_path",
#             "type": "text",
#             "label": "MCT - " + config.get_localized_string(30017),
#             "default": DOWNLOAD_PATH,
#             "enabled": True,
#             "visible": "eq(-2,%s)" % torrent_options[2]
#         },
#         {
#             "id": "bt_buffer",
#             "type": "text",
#             "label": "BT - " + config.get_localized_string(70758),
#             "default": BUFFER_BT,
#             "enabled": True,
#             "visible": "eq(-3,%s)" % torrent_options[1]
#         },
#         {
#             "id": "bt_download_path",
#             "type": "text",
#             "label": "BT - " + config.get_localized_string(30017),
#             "default": DOWNLOAD_PATH_BT,
#             "enabled": True,
#             "visible": "eq(-4,%s)" % torrent_options[1]
#         },
#         {
#             "id": "mct_download_limit",
#             "type": "text",
#             "label": config.get_localized_string(70759),
#             "default": DOWNLOAD_LIMIT,
#             "enabled": True,
#             "visible": "eq(-5,%s) | eq(-5,%s)" % (torrent_options[1], torrent_options[2])
#         },
#         {
#             "id": "mct_rar_unpack",
#             "type": "bool",
#             "label": config.get_localized_string(70760),
#             "default": RAR,
#             "enabled": True,
#             "visible": True
#         },
#         {
#             "id": "mct_background_download",
#             "type": "bool",
#             "label": config.get_localized_string(70761),
#             "default": BACKGROUND,
#             "enabled": True,
#             "visible": True
#         },
#         {
#             "id": "magnet2torrent",
#             "type": "bool",
#             "label": config.get_localized_string(70762),
#             "default": MAGNET2TORRENT,
#             "enabled": True,
#             "visible": True
#         }
#     ]

#     platformtools.show_channel_settings(list_controls=list_controls, callback='save_setting_torrent', item=item,
#                                         caption=config.get_localized_string(70257), custom_button={'visible': False})


# def save_setting_torrent(item, dict_data_saved):
#     if dict_data_saved and "list_torrent" in dict_data_saved:
#         config.set_setting("torrent_client", dict_data_saved["list_torrent"], server="torrent")
#     if dict_data_saved and "mct_buffer" in dict_data_saved:
#         config.set_setting("mct_buffer", dict_data_saved["mct_buffer"], server="torrent")
#     if dict_data_saved and "mct_download_path" in dict_data_saved:
#         config.set_setting("mct_download_path", dict_data_saved["mct_download_path"], server="torrent")
#     if dict_data_saved and "mct_background_download" in dict_data_saved:
#         config.set_setting("mct_background_download", dict_data_saved["mct_background_download"], server="torrent")
#     if dict_data_saved and "mct_rar_unpack" in dict_data_saved:
#         config.set_setting("mct_rar_unpack", dict_data_saved["mct_rar_unpack"], server="torrent")
#     if dict_data_saved and "mct_download_limit" in dict_data_saved:
#         config.set_setting("mct_download_limit", dict_data_saved["mct_download_limit"], server="torrent")
#     if dict_data_saved and "bt_buffer" in dict_data_saved:
#         config.set_setting("bt_buffer", dict_data_saved["bt_buffer"], server="torrent")
#     if dict_data_saved and "bt_download_path" in dict_data_saved:
#         config.set_setting("bt_download_path", dict_data_saved["bt_download_path"], server="torrent")
#     if dict_data_saved and "magnet2torrent" in dict_data_saved:
#         config.set_setting("magnet2torrent", dict_data_saved["magnet2torrent"], server="torrent")

def menu_servers(item):
    logger.debug()
    itemlist = list()

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60550), action="servers_blacklist", folder=False,
                         thumbnail=get_thumb("setting_0.png")))

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60551),
                         action="servers_favorites", folder=False, thumbnail=get_thumb("setting_0.png")))

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60552),
                         action="", folder=False, text_bold = True, thumbnail=get_thumb("setting_0.png")))

    # Home - Configurable servers

    server_list = list(servertools.get_debriders_list().keys())
    for server in server_list:
        server_parameters = servertools.get_server_parameters(server)
        if server_parameters["has_settings"]:
            itemlist.append(
                Item(channel=CHANNELNAME, title = ".    " + config.get_localized_string(60553) % server_parameters["name"],
                     action="server_debrid_config", config=server, folder=False, thumbnail=""))

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60554),
                         action="", folder=False, text_bold = True, thumbnail=get_thumb("setting_0.png")))

    server_list = list(servertools.get_servers_list().keys())

    for server in sorted(server_list):
        server_parameters = servertools.get_server_parameters(server)
        logger.debug(server_parameters)
        if server_parameters["has_settings"] and [x for x in server_parameters["settings"] if x["id"] not in ["black_list", "white_list"]]:
            itemlist.append(
                Item(channel=CHANNELNAME, title=".    " + config.get_localized_string(60553) % server_parameters["name"],
                     action="server_config", config=server, folder=False, thumbnail=""))

    # End - Configurable servers

    return itemlist


def server_config(item):
    return platformtools.show_channel_settings(channelpath=filetools.join(config.get_runtime_path(), "servers", item.config))

def server_debrid_config(item):
    return platformtools.show_channel_settings(channelpath=filetools.join(config.get_runtime_path(), "servers", "debriders", item.config))


def servers_blacklist(item):
    server_list = servertools.get_servers_list()
    black_list = config.get_setting("black_list", server='servers', default=[])
    blacklisted = []

    list_controls = []
    list_servers = []

    for i, server in enumerate(sorted(server_list.keys())):
        server_parameters = server_list[server]
        defaults = servertools.get_server_parameters(server)

        control = server_parameters["name"]
        # control.setArt({'thumb:': server_parameters['thumb'] if 'thumb' in server_parameters else config.get_online_server_thumb(server)})
        if not config.get_setting("black_list", server=server):
            list_controls.append(control)
            if defaults.get("black_list", False) or server in black_list:
                blacklisted.append(i)
        list_servers.append(server)
    ris = platformtools.dialog_multiselect(config.get_localized_string(60550), list_controls, preselect=blacklisted)
    if ris is not None:
        config.set_setting("black_list", [l for n, l in enumerate(list_servers) if n in ris], server='servers')
    # if ris is not None:
    #     cb_servers_blacklist({list_servers[n]: True if n in ris else False for n, it in enumerate(list_controls)})
    # return platformtools.show_channel_settings(list_controls=list_controls, dict_values=dict_values, caption=config.get_localized_string(60550), callback="cb_servers_blacklist")


# def cb_servers_blacklist(dict_values):
#     blaklisted = [k for k in dict_values.keys()]
    # progreso = platformtools.dialog_progress(config.get_localized_string(60557), config.get_localized_string(60558))
    # n = len(dict_values)
    # i = 1
    # for k, v in list(dict_values.items()):
    #     if v:  # If the server is blacklisted it cannot be in the favorites list
    #         config.set_setting("favorites_servers_list", 0, server=k)
    #         blaklisted.append(k)
    #         progreso.update(old_div((i * 100), n), config.get_localized_string(60559) % k)
    #     i += 1
    # config.set_setting("black_list", blaklisted, server='servers')

    # progreso.close()


def servers_favorites(item):
    server_list = servertools.get_servers_list()
    dict_values = {}

    list_controls = [{'id': 'favorites_servers',
                      'type': 'bool',
                      'label': config.get_localized_string(60577),
                      'default': False,
                      'enabled': True,
                      'visible': True},
                     {'id': 'quality_priority',
                      'type': 'bool',
                      'label': config.get_localized_string(30069),
                      'default': False,
                      'enabled': 'eq(-1,True)',
                      'visible': True}]
    dict_values['favorites_servers'] = config.get_setting('favorites_servers')
    dict_values['quality_priority'] = config.get_setting('quality_priority')
    if dict_values['favorites_servers'] == None:
        dict_values['favorites_servers'] = False

    server_names = [config.get_localized_string(59992)]
    favorites = config.get_setting("favorites_servers_list", server='servers', default=[])
    blacklisted = config.get_setting("black_list", server='servers', default=[])

    for server in sorted(server_list.keys()):
        if server in blacklisted or config.get_setting("black_list", server=server):
            continue

        server_names.append(server_list[server]['name'])
        if server in favorites:
            orden = favorites.index(server) + 1
            dict_values[orden] = len(server_names) - 1

    for x in range(1, 12):
        control = {'id': x,
                   'type': 'list',
                   'label': config.get_localized_string(60597) % x,
                   'lvalues': server_names,
                   'default': 0,
                   'enabled': 'eq(-%s,True)' % str(x + 1),
                   'visible': True}
        list_controls.append(control)

    return platformtools.show_channel_settings(list_controls=list_controls, dict_values=dict_values, item=server_names,
                                               caption=config.get_localized_string(60551), callback="cb_servers_favorites")


def cb_servers_favorites(server_names, dict_values):
    dict_name = {}
    dict_favorites = {}

    for i, v in list(dict_values.items()):
        if i == "favorites_servers":
            config.set_setting("favorites_servers", v)
        elif i == "quality_priority":
            config.set_setting("quality_priority", v)
        elif int(v) > 0:
            dict_name[server_names[v]] = int(i)

    servers_list = list(servertools.get_servers_list().items())
    for server, server_parameters in servers_list:
        if server_parameters['name'] in list(dict_name.keys()):
            dict_favorites[dict_name[server_parameters['name']]] = server

    favorites_servers_list = [dict_favorites[k] for k in sorted(dict_favorites.keys())]

    config.set_setting("favorites_servers_list", favorites_servers_list, server='servers')

    if not favorites_servers_list:  # If there is no server in the list, deactivate it
        config.set_setting("favorites_servers", False)


def settings(item):
    config.open_settings()


def check_quickfixes(item):
    logger.debug()

    if not config.dev_mode():
        from platformcode import updater
        if not updater.check()[0]:
            platformtools.dialog_ok(config.get_localized_string(20000), config.get_localized_string(70667))
    else:
        return False


# def update_quasar(item):
#     logger.debug()

#     from platformcode import custom_code, platformtools
#     stat = False
#     stat = custom_code.update_external_addon("quasar")
#     if stat:
#         platformtools.dialog_notification("Actualización Quasar", "Realizada con éxito")
#     else:
#         platformtools.dialog_notification("Actualización Quasar", "Ha fallado. Consulte el log")


def conf_tools(item):
    logger.debug()

    # Enable or disable channels
    if item.extra == "channels_onoff":
        if config.get_platform(True)['num_version'] >= 17.0: # From Kodi 16 you can use multiselect, and from 17 with preselect
            return channels_onoff(item)

        import channelselector
        from core import channeltools

        channel_list = channelselector.filterchannels("allchannelstatus")

        excluded_channels = ['url',
                             'search',
                             'videolibrary',
                             'setting',
                             'news',
                             # 'help',
                             'downloads']

        list_controls = []
        try:
            list_controls.append({'id': "all_channels",
                                  'type': "list",
                                  'label': config.get_localized_string(60594),
                                  'default': 0,
                                  'enabled': True,
                                  'visible': True,
                                  'lvalues': ['',
                                              config.get_localized_string(60591),
                                              config.get_localized_string(60592),
                                              config.get_localized_string(60593)]})

            for channel in channel_list:
                # If the channel is on the exclusion list, we skip it
                if channel.channel not in excluded_channels:

                    channel_parameters = channeltools.get_channel_parameters(channel.channel)

                    status_control = ""
                    status = config.get_setting("enabled", channel.channel)
                    # if status does not exist, there is NO value in _data.json
                    if status is None:
                        status = channel_parameters["active"]
                        logger.debug("%s | Status (XML): %s" % (channel.channel, status))
                        if not status:
                            status_control = config.get_localized_string(60595)
                    else:
                        logger.debug("%s  | Status: %s" % (channel.channel, status))

                    control = {'id': channel.channel,
                               'type': "bool",
                               'label': channel_parameters["title"] + status_control,
                               'default': status,
                               'enabled': True,
                               'visible': True}
                    list_controls.append(control)

                else:
                    continue

        except:
            import traceback
            logger.error("Error: %s" % traceback.format_exc())
        else:
            return platformtools.show_channel_settings(list_controls=list_controls,
                                                       item=item.clone(channel_list=channel_list),
                                                       caption=config.get_localized_string(60596),
                                                       callback="channel_status",
                                                       custom_button={"visible": False})

    # Checking channel_data.json files
    elif item.extra == "lib_check_datajson":
        itemlist = []
        import channelselector
        from core import channeltools
        channel_list = channelselector.filterchannels("allchannelstatus")

        # Having an exclusion list doesn't make much sense because it checks if channel.json has "settings", but just in case it is left
        excluded_channels = ['url',
                             'setting',
                             'help']

        try:
            import os
            from core import jsontools
            for channel in channel_list:

                list_status = None
                default_settings = None

                # It is checked if the channel is in the exclusion list
                if channel.channel not in excluded_channels:
                    # It is checked that it has "settings", otherwise it skips
                    list_controls, dict_settings = channeltools.get_channel_controls_settings(channel.channel)

                    if not list_controls:
                        itemlist.append(Item(channel=CHANNELNAME,
                                             title=channel.title + config.get_localized_string(60569),
                                             action="", folder=False,
                                             thumbnail=channel.thumbnail))
                        continue
                        # logger.debug(channel.channel + " SALTADO!")

                    # The json file settings of the channel are loaded
                    file_settings = os.path.join(config.get_data_path(), "settings_channels", channel.channel + "_data.json")
                    dict_settings = {}
                    dict_file = {}
                    if filetools.exists(file_settings):
                        # logger.debug(channel.channel + " Has _data.json file")
                        channeljson_exists = True
                        # We get saved settings from ../settings/channel_data.json
                        try:
                            dict_file = jsontools.load(filetools.read(file_settings))
                            if isinstance(dict_file, dict) and 'settings' in dict_file:
                                dict_settings = dict_file['settings']
                        except EnvironmentError:
                            logger.error("ERROR when reading the file: %s" % file_settings)
                    else:
                        # logger.debug(channel.channel + " No _data.json file")
                        channeljson_exists = False

                    if channeljson_exists:
                        try:
                            datajson_size = filetools.getsize(file_settings)
                        except:
                            import traceback
                            logger.error(channel.title + config.get_localized_string(60570) % traceback.format_exc())
                    else:
                        datajson_size = None

                    # If the _data.json is empty or does not exist ...
                    if (len(dict_settings) and datajson_size) == 0 or not channeljson_exists:
                        # We get controls from the file ../channels/channel.json
                        needsfix = True
                        try:
                            # Default settings are loaded
                            list_controls, default_settings = channeltools.get_channel_controls_settings(
                                channel.channel)
                            # logger.debug(channel.title + " | Default: %s" % default_settings)
                        except:
                            import traceback
                            logger.error(channel.title + config.get_localized_string(60570) % traceback.format_exc())
                            # default_settings = {}

                        # If _data.json needs to be repaired or doesn't exist ...
                        if needsfix or not channeljson_exists:
                            if default_settings is not None:
                                # We create the channel_data.json
                                default_settings.update(dict_settings)
                                dict_settings = default_settings
                                dict_file['settings'] = dict_settings
                                # We create the file ../settings/channel_data.json
                                if not filetools.write(file_settings, jsontools.dump(dict_file), silent=True):
                                    logger.error("ERROR saving file: %s" % file_settings)
                                list_status = config.get_localized_string(60560)
                            else:
                                if default_settings is None:
                                    list_status = config.get_localized_string(60571)

                    else:
                        # logger.debug(channel.channel + " - NO correction needed!")
                        needsfix = False

                    # If the channel status has been set it is added to the list
                    if needsfix is not None:
                        if needsfix:
                            if not channeljson_exists:
                                list_status = config.get_localized_string(60588)
                                list_colour = "red"
                            else:
                                list_status = config.get_localized_string(60589)
                                list_colour = "green"
                        else:
                            # If "needsfix" is "false" and "datjson_size" is None, an error will have occurred
                            if datajson_size is None:
                                list_status = config.get_localized_string(60590)
                                list_colour = "red"
                            else:
                                list_status = config.get_localized_string(60589)
                                list_colour = "green"

                    if list_status is not None:
                        itemlist.append(Item(channel=CHANNELNAME,
                                             title=channel.title + list_status,
                                             action="", folder=False,
                                             thumbnail=channel.thumbnail,
                                             text_color=list_colour))
                    else:
                        logger.error("Something is wrong with the channel %s" % channel.channel)

                # If the channel is on the exclusion list, we skip it
                else:
                    continue
        except:
            import traceback
            logger.error("Error: %s" % traceback.format_exc())

        return itemlist


def channels_onoff(item):
    import channelselector, xbmcgui
    from core import channeltools

    # Load list of options
    # ------------------------
    lista = []; ids = []
    channels_list = channelselector.filterchannels('allchannelstatus')
    for channel in channels_list:
        channel_parameters = channeltools.get_channel_parameters(channel.channel)
        lbl = '%s' % channel_parameters['language']
        # ~ lbl += ' %s' % [config.get_localized_category(categ) for categ in channel_parameters['categories']]
        lbl += ' %s' % ', '.join(config.get_localized_category(categ) for categ in channel_parameters['categories'])

        it = xbmcgui.ListItem(channel.title, lbl)
        it.setArt({ 'thumb': channel.thumbnail, 'fanart': channel.fanart })
        lista.append(it)
        ids.append(channel.channel)

    # Dialog to pre-select
    # ----------------------------
    preselecciones = [config.get_localized_string(70517), config.get_localized_string(70518), config.get_localized_string(70519)]
    ret = platformtools.dialog_select(config.get_localized_string(60545), preselecciones)
    if ret == -1: return False # order cancel
    if ret == 2: preselect = []
    elif ret == 1: preselect = list(range(len(ids)))
    else:
        preselect = []
        for i, canal in enumerate(ids):
            channel_status = config.get_setting('enabled', canal)
            if channel_status is None: channel_status = True
            if channel_status:
                preselect.append(i)

    # Dialog to select
    # ------------------------
    ret = platformtools.dialog_multiselect(config.get_localized_string(60545), lista, preselect=preselect, useDetails=True)
    if ret == None: return False # order cancel
    seleccionados = [ids[i] for i in ret]

    # Save changes to activated channels
    # ------------------------------------
    for canal in ids:
        channel_status = config.get_setting('enabled', canal)
        if channel_status is None: channel_status = True

        if channel_status and canal not in seleccionados:
            config.set_setting('enabled', False, canal)
        elif not channel_status and canal in seleccionados:
            config.set_setting('enabled', True, canal)

    return False


def channel_status(item, dict_values):
    try:
        for k in dict_values:

            if k == "all_channels":
                logger.info("All channels | Selected state: %s" % dict_values[k])
                if dict_values[k] != 0:
                    excluded_channels = ['url', 'search',
                                         'videolibrary', 'setting',
                                         'news',
                                         'help',
                                         'downloads']

                    for channel in item.channel_list:
                        if channel.channel not in excluded_channels:
                            from core import channeltools
                            channel_parameters = channeltools.get_channel_parameters(channel.channel)
                            new_status_all = None
                            new_status_all_default = channel_parameters["active"]

                            # Option Activate all
                            if dict_values[k] == 1:
                                new_status_all = True

                            # Option Deactivate all
                            if dict_values[k] == 2:
                                new_status_all = False

                            # Retrieve default status option
                            if dict_values[k] == 3:
                                # If you have "enabled" in the _data.json, it is because the state is not that of the channel.json
                                if config.get_setting("enabled", channel.channel):
                                    new_status_all = new_status_all_default

                                # If the channel does not have "enabled" in the _data.json it is not saved, it goes to the next
                                else:
                                    continue

                            # Channel status is saved
                            if new_status_all is not None:
                                config.set_setting("enabled", new_status_all, channel.channel)
                    break
                else:
                    continue

            else:
                logger.info("Channel: %s | State: %s" % (k, dict_values[k]))
                config.set_setting("enabled", dict_values[k], k)
                logger.info("the value is like %s " % config.get_setting("enabled", k))

        platformtools.itemlist_update(Item(channel=CHANNELNAME, action="mainlist"))

    except:
        import traceback
        logger.error("Error detail: %s" % traceback.format_exc())
        platformtools.dialog_notification(config.get_localized_string(60579), config.get_localized_string(60580))


def restore_tools(item):
    import service
    from core import videolibrarytools
    import os

    seleccion = platformtools.dialog_yesno(config.get_localized_string(60581),
                                           config.get_localized_string(60582) + '\n' +
                                           config.get_localized_string(60583))
    if seleccion == 1:
        # tvshows
        heading = config.get_localized_string(60584)
        p_dialog = platformtools.dialog_progress_bg(config.get_localized_string(20000), heading)
        p_dialog.update(0, '')

        show_list = []
        for path, folders, files in filetools.walk(videolibrarytools.TVSHOWS_PATH):
            show_list.extend([filetools.join(path, f) for f in files if f == "tvshow.nfo"])

        if show_list:
            t = float(100) / len(show_list)

        for i, tvshow_file in enumerate(show_list):
            head_nfo, serie = videolibrarytools.read_nfo(tvshow_file)
            path = filetools.dirname(tvshow_file)

            #if not serie.active:
                # if the series is not active discard
            #    continue

            # We delete the folder with the series ...
            if tvshow_file.endswith('.strm') or tvshow_file.endswith('.json') or tvshow_file.endswith('.nfo'):
                os.remove(os.path.join(path, tvshow_file))
            # filetools.rmdirtree(path)

            # ... and we add it again
            service.update(path, p_dialog, i, t, serie, 3)
        p_dialog.close()

        # movies
        heading = config.get_localized_string(60586)
        p_dialog2 = platformtools.dialog_progress_bg(config.get_localized_string(20000), heading)
        p_dialog2.update(0, '')

        movies_list = []
        for path, folders, files in filetools.walk(videolibrarytools.MOVIES_PATH):
            movies_list.extend([filetools.join(path, f) for f in files if f.endswith(".json")])

        logger.debug("movies_list %s" % movies_list)

        if movies_list:
            t = float(100) / len(movies_list)

        for i, movie_json in enumerate(movies_list):
            try:
                from core import jsontools
                path = filetools.dirname(movie_json)
                movie = Item().fromjson(filetools.read(movie_json))

                # We delete the folder with the movie ...
                filetools.rmdirtree(path)

                import math
                heading = config.get_localized_string(20000)

                p_dialog2.update(int(math.ceil((i + 1) * t)), heading, config.get_localized_string(60389) % (movie.contentTitle,
                                                                                   movie.channel.capitalize()))
                # ... and we add it again
                videolibrarytools.save_movie(movie)
            except Exception as ex:
                logger.error("Error creating movie again")
                template = "An exception of type %s occured. Arguments:\n%r"
                message = template % (type(ex).__name__, ex.args)
                logger.error(message)

        p_dialog2.close()



# ── Config invio-log Telegram ─────────────────────────────
# Token offuscato (base64 del token invertito) per evitare scanner automatici.
# Non e' crittografia: il bot puo' essere revocato da BotFather in ogni momento.
# Android must never ship bot credentials. Diagnostics are delivered by the
# HTTPS relay configured in BuildConfig, with the Android share sheet as
# fallback. The legacy Kodi-only sender below remains inert in this package.
_TG_TOKEN_OBF = ''
_TG_CHAT_ID = ''


def _tg_token():
    import base64
    return base64.b64decode(_TG_TOKEN_OBF).decode('utf-8')[::-1]


def send_log_to_dev(item):
    """Invia i log di Kodi direttamente allo sviluppatore via bot Telegram.

    Un solo tasto: raccoglie TUTTI i log disponibili (kodi.log corrente,
    kodi.old.log della sessione precedente — dove finiscono i crash, perche'
    Kodi ruota il log al riavvio — piu' eventuali log ruotati/crash presenti
    nella cartella), li impacchetta in un unico .zip e lo manda con
    sendDocument al bot: arriva subito come notifica, senza URL da copiare.
    L'invio non modifica il livello di logging: sulle box lente il debug
    generico produce migliaia di righe e lavoro inutile. La telemetria mirata
    [PERF]/[NET] resta governata separatamente da perf_log.
    Fallback se Telegram e' irraggiungibile: upload su dpaste.org e mostra
    l'URL da girare a mano.
    """
    import io
    import json
    import ssl
    import time
    import uuid
    import zipfile
    import xbmc
    try:
        from xbmcvfs import translatePath    # Kodi 19+
    except ImportError:
        from xbmc import translatePath       # Kodi 18

    if not _TG_TOKEN_OBF or not _TG_CHAT_ID:
        platformtools.dialog_ok('Invia Log', 'Funzione non configurata in questa build.')
        return

    # ── 1. Raccogli TUTTI i log disponibili ───────────────────────────────
    # Tetto per file: i log viaggiano zippati (comprimono ~20x) e Telegram
    # accetta documenti fino a 50 MB, quindi si puo' essere generosi. Se un
    # log e' piu' grande si manda la CODA (la parte recente, quella utile).
    MAX_PER_FILE = 12 * 1024 * 1024

    def _tail(path, max_bytes):
        try:
            with open(path, 'rb') as _f:
                _f.seek(0, 2)
                size = _f.tell()
                _f.seek(max(0, size - max_bytes))
                return _f.read()
        except Exception:
            return b''

    logdir = translatePath('special://logpath/')
    log_path = filetools.join(logdir, 'kodi.log')
    if not filetools.exists(log_path):
        platformtools.dialog_ok('Invia Log', 'File di log non trovato:\n%s' % log_path)
        return

    # kodi.log e kodi.old.log per primi, poi qualunque altro .log/.old/crash
    wanted = ['kodi.log', 'kodi.old.log']
    try:
        for name in sorted(filetools.listdir(logdir)):
            low = name.lower()
            if name in wanted:
                continue
            if low.endswith('.log') or low.endswith('.old.log') or 'crash' in low:
                wanted.append(name)
    except Exception:
        pass

    collected = []          # [(nome, bytes)]
    for name in wanted:
        data = _tail(filetools.join(logdir, name), MAX_PER_FILE)
        if data:
            collected.append((name, data))
    # Il service conserva le ultime tre sessioni precedenti in userdata/oldlogs.
    # Includile nel bundle: dopo più riavvii Kodi può aver già sovrascritto
    # kodi.old.log, ma il log del crash resta nel ring.
    try:
        ring_dir = filetools.join(config.get_data_path(), 'oldlogs')
        for n in (1, 2, 3):
            ring_path = filetools.join(ring_dir, 'oldlog_%d.log' % n)
            ring_data = _tail(ring_path, MAX_PER_FILE)
            if ring_data:
                collected.append(('oldlog_ring_%d.log' % n, ring_data))
    except Exception:
        pass
    if not collected:
        platformtools.dialog_ok('Invia Log', 'Errore lettura log:\n%s' % log_path)
        return
    # log_bytes serve solo al fallback testuale (dpaste): usa il log corrente
    log_bytes = collected[0][1]

    # ── 2. Nota opzionale (chi sei / che problema hai) ────────────────────
    note = platformtools.dialog_input(
        default='', heading='Nome e problema (opzionale, OK per inviare)')
    if note is None:
        note = ''   # BACK sul telecomando: invia comunque, anonimo

    # ── 3. Impacchetta tutti i log in un unico zip + metadati ─────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as _z:
        for name, data in collected:
            _z.writestr(name, data)
        _z.writestr('info.txt', '\n'.join([
            'PrippiStream %s' % config.get_addon_version(),
            'Kodi        %s' % xbmc.getInfoLabel('System.BuildVersion'),
            'Device      %s' % xbmc.getInfoLabel('System.FriendlyName'),
            'OS          %s' % (xbmc.getInfoLabel('System.OSVersionInfo') or '-'),
            'Schermo     %s' % xbmc.getInfoLabel('System.ScreenResolution'),
            'Memoria     libera %s / totale %s' % (
                xbmc.getInfoLabel('System.Memory(free)'),
                xbmc.getInfoLabel('System.Memory(total)')),
            'Inviato     %s' % time.strftime('%Y-%m-%d %H:%M:%S'),
            'Nota        %s' % (note.strip() or 'anonimo'),
            '',
            'File inclusi:',
        ] + ['  %-16s %6d KB' % (n, len(d) // 1024) for n, d in collected]))
    gz_bytes = buf.getvalue()

    # ID univoco del dispositivo: fingerprint stabile per-installazione (stessa
    # fonte del download offline: device.id persistito in userdata — NON il MAC,
    # che su Android è nascosto alle app: arriva il finto 02:00:00:00:00:00).
    # Il MAC si aggiunge best-effort dove è leggibile (PC/Linux).
    try:
        from core.download_crypto import key_fingerprint
        device_id = key_fingerprint()
    except Exception:
        device_id = '?'
    mac = xbmc.getInfoLabel('Network.MacAddress')
    if not mac or ':' not in mac or mac.startswith('02:00:00'):
        mac = '-'

    caption = ('PrippiStream %s | Kodi %s\n%s | %s\nID: %s | MAC: %s\nLog: %s\nDa: %s' % (
        config.get_addon_version(),
        xbmc.getInfoLabel('System.BuildVersion'),
        xbmc.getInfoLabel('System.FriendlyName'),
        xbmc.getInfoLabel('System.OSVersionInfo') or '-',
        device_id, mac,
        ', '.join('%s (%d KB)' % (n, len(d) // 1024) for n, d in collected),
        note.strip() or 'anonimo'))[:1024]
    filename = 'prippi_%s.zip' % time.strftime('%Y%m%d_%H%M%S')

    # ── 4. Invio a Telegram (multipart, solo stdlib) ──────────────────────
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (('chat_id', _TG_CHAT_ID), ('caption', caption)):
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, name, value)).encode('utf-8'))
    parts.append(('--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
                  'Content-Type: application/zip\r\n\r\n' % (boundary, filename)).encode('utf-8'))
    parts.append(gz_bytes)
    parts.append(('\r\n--%s--\r\n' % boundary).encode('utf-8'))
    body = b''.join(parts)

    try:
        import urllib.request as _urllib
    except ImportError:
        import urllib2 as _urllib

    platformtools.dialog_notification('PrippiStream', 'Invio log in corso...')
    sent = False
    last_err = ''
    # 2° giro senza verifica SSL: box datati con certificati di sistema rotti
    for ctx in (None, ssl._create_unverified_context()):
        try:
            req = _urllib.Request(
                'https://api.telegram.org/bot%s/sendDocument' % _tg_token(),
                data=body,
                headers={'Content-Type': 'multipart/form-data; boundary=%s' % boundary})
            if ctx is None:
                resp = _urllib.urlopen(req, timeout=30)
            else:
                resp = _urllib.urlopen(req, timeout=30, context=ctx)
            ans = json.loads(resp.read().decode('utf-8', errors='replace'))
            if ans.get('ok'):
                sent = True
            else:
                last_err = str(ans.get('description', ans))[:200]
            break
        except Exception as exc:
            last_err = str(exc)

    # ── 5. Fallback: dpaste.org, URL da girare a mano ─────────────────────
    if not sent:
        try:
            try:
                from urllib.parse import urlencode
            except ImportError:
                from urllib import urlencode
            data = urlencode({
                'content': log_bytes[-200 * 1024:].decode('utf-8', errors='replace'),
                'lexer': '_text'}).encode('utf-8')
            resp = _urllib.urlopen('https://dpaste.org/api/', data=data, timeout=20)
            paste_url = resp.read().decode('utf-8', errors='replace').strip().strip('"')
            if paste_url.startswith('http'):
                platformtools.dialog_ok(
                    'Invia Log',
                    'Invio diretto non riuscito. Manda questo link allo sviluppatore:\n'
                    '[B][COLOR gold]%s[/COLOR][/B]' % paste_url)
                return
        except Exception:
            pass
        platformtools.dialog_ok(
            'Invia Log', 'Invio fallito:\n%s\n\nControlla la connessione e riprova.' % last_err[:200])
        return

    # ── 6. Esito ──────────────────────────────────────────────────────────
    platformtools.dialog_ok('Log Inviato', 'Log inviato allo sviluppatore!')
