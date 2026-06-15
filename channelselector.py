# -*- coding: utf-8 -*-

import glob, os

from core.item import Item
from platformcode import config, logger
addon = config.__settings__


def getmainlist(view="thumb_"):
    logger.debug()
    itemlist = list()

    # Netflix-style StreamingCommunity home
    itemlist.append(Item(
        title='[B]▶ PrippiStream — Vista Netflix[/B]',
        channel='channelselector',
        action='open_netflix_home',
        thumbnail=get_thumb("streamingcommunity.png", view),
        category='Netflix Home',
        viewmode='thumbnails',
    ))

    thumb_setting = "setting_%s.png" % 0
    itemlist.append(Item(title=config.get_localized_string(30100), channel="setting", action="settings",
                         thumbnail=get_thumb(thumb_setting, view), category=config.get_localized_string(30100), viewmode="list", folder=False))
    return itemlist


def filterchannels(category, view="thumb_"):
    from core import channeltools
    logger.debug('Filter Channels ' + category)

    channelslist = []

    # If category = "allchannelstatus" is that we are activating / deactivating channels
    appenddisabledchannels = False
    if category == "allchannelstatus":
        category = "all"
        appenddisabledchannels = True

    channel_path = os.path.join(config.get_runtime_path(), 'channels', '*.json')
    logger.debug("channel_path = %s" % channel_path)

    channel_files = glob.glob(channel_path)
    logger.debug("channel_files found %s" % (len(channel_files)))

    # Channel Language
    channel_language = auto_filter()
    logger.debug("channel_language=%s" % channel_language)

    for channel_path in channel_files:
        logger.debug("channel in for = %s" % channel_path)

        channel = os.path.basename(channel_path).replace(".json", "")

        try:
            channel_parameters = channeltools.get_channel_parameters(channel)

            if channel_parameters["channel"] == 'community':
                continue

            # If it's not a channel we skip it
            if not channel_parameters["channel"]:
                continue
            logger.debug("channel_parameters=%s" % repr(channel_parameters))

            # If you prefer the banner and the channel has it, now change your mind
            if view == "banner_" and "banner" in channel_parameters:
                channel_parameters["thumbnail"] = channel_parameters["banner"]

            # if the channel is deactivated the channel is not shown in the list
            if not channel_parameters["active"]:
                continue

            # The channel is skipped if it is not active and we are not activating / deactivating the channels
            channel_status = config.get_setting("enabled", channel_parameters["channel"])

            if channel_status is None:
                # if channel_status does not exist, there is NO value in _data.json.
                # as we got here (the channel is active in channel.json), True is returned
                channel_status = True

            if not channel_status:
                # if we get the list of channels from "activate / deactivate channels", and the channel is deactivated
                # we show it, if we are listing all the channels from the general list and it is deactivated, it is not shown
                if not appenddisabledchannels:
                    continue

            if channel_language != "all" and "*" not in channel_parameters["language"] \
                 and channel_language not in str(channel_parameters["language"]):
                continue

            # The channel is skipped if it is in a filtered category
            if category != "all" and category not in channel_parameters["categories"]:
                continue

            # If you have configuration we add an item in the context
            context = []
            if channel_parameters["has_settings"]:
                context.append({"title": config.get_localized_string(70525), "channel": "setting", "action": "channel_config",
                                "config": channel_parameters["channel"]})

            channel_info = set_channel_info(channel_parameters)
            # If it has come this far, add it
            channelslist.append(Item(title=channel_parameters["title"], channel=channel_parameters["channel"],
                                     action="mainlist", thumbnail=channel_parameters["thumbnail"],
                                     fanart=channel_parameters["fanart"], plot=channel_info, category=channel_parameters["title"],
                                     language=channel_parameters["language"], viewmode="list", context=context))

        except:
            logger.error("An error occurred while reading the channel data '%s'" % channel)
            import traceback
            logger.error(traceback.format_exc())

    channelslist.sort(key=lambda item: item.title.lower().strip())

    return channelslist


def get_thumb(thumb_name, view="thumb_"):
    from core import filetools
    if thumb_name.startswith('http'):
        return thumb_name
    elif config.get_setting('enable_custom_theme') and config.get_setting('custom_theme') and filetools.isfile(config.get_setting('custom_theme') + view + thumb_name):
        media_path = config.get_setting('custom_theme')
    else:
        icon_pack_name = config.get_setting('icon_set', default="default")
        media_path = filetools.join("https://raw.githubusercontent.com/Stream4me/media/master/themes", icon_pack_name)
    return filetools.join(media_path, view + thumb_name)


def set_channel_info(parameters):
    logger.debug()

    info = ''
    language = ''
    content = ''
    langs = parameters['language']
    lang_dict = {'ita':'Italiano',
                 'sub-ita':'Sottotitolato in Italiano',
                 '*':'Italiano, Sottotitolato in Italiano'}

    for lang in langs:

        if lang in lang_dict:
            if language != '' and language != '*':
                language = '%s, %s' % (language, lang_dict[lang])
            else:
                language = lang_dict[lang]
        if lang == '*':
            break

    categories = parameters['categories']
    for cat in categories:
        if content != '':
            content = '%s, %s' % (content, config.get_localized_category(cat))
        else:
            content = config.get_localized_category(cat)

    info = '[B]' + config.get_localized_string(70567) + ' [/B]' + content + '\n\n'
    info += '[B]' + config.get_localized_string(70568) + ' [/B] ' + language
    return info


def auto_filter(auto_lang=False):
    list_lang = ['ita', 'vos', 'sub-ita']
    if config.get_setting("channel_language") == 'auto' or auto_lang == True:
        lang = config.get_language()

    else:
        lang = config.get_setting("channel_language", default="all")

    if lang not in list_lang:
        lang = 'all'

    return lang
