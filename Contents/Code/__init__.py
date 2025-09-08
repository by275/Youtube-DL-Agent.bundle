#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
import json
import os
import re
import urllib2

from io import open

PTN_TITLE = re.compile(r'\[[a-zA-Z0-9_-]+\]')


def Start():
    Log("Starting up ...")


class YoutubeDLAgent(Agent.TV_Shows):
    name = 'Youtube-DL'
    primary_provider = True
    fallback_agent = None
    contributes_to = None
    languages = [Locale.Language.English, ]
    accepts_from = ['com.plexapp.agents.localmedia']

    def search(self, results, media, lang, manual=False):
        Log("======== SEARCH START ========")

        media_file = urllib2.unquote(media.filename)
        infojson = os.path.splitext(media_file)[0].strip() + ".info.json"
        if os.path.isfile(infojson):
            try:
                with open(infojson, encoding="utf-8") as f:
                    data = json.load(f)
                    results.Append(MetadataSearchResult(
                        id=data.get("playlist_id"),
                        name=media.title,
                        year=data.get("upload_date", "")[:4] or None,
                        lang=lang,
                        score=100
                    ))
                    results.Sort('score', descending=True)
            except Exception as e:
                Log("Failed to load infojson '{}': {}".format(infojson, e))

        Log("======== SEARCH END ========")

    def update(self, metadata, media, lang):
        Log("======== UPDATE START ========")

        # show-level metadata from pl_infojson
        metadict = {}
        file = ""
        for s in media.seasons if media else []:
            for e in media.seasons[s].episodes:
                file = media.seasons[s].episodes[e].items[0].parts[0].file
                if file:
                    break
        if file:
            dirname = os.path.dirname(file)
            filenames = ["", "playlist", os.path.basename(dirname)]
            filenames = [(f + ".info.json" if f else "info.json") for f in filenames]
            for filename in filenames:
                pl_infojson = os.path.join(dirname, filename)
                if os.path.isfile(pl_infojson):
                    try:
                        with open(pl_infojson, encoding="utf-8") as f:
                            data = json.load(f)
                            metadict = {
                                "title": data.get("title", "Untitled"),
                                "summary": data.get("description", ""),
                                "studio": data.get("uploader", ""),
                                "tags": data.get("tags", [])
                                # originally_available_at
                                # content_rating
                                # genres
                                # collections
                                # ratings
                                # posters
                                # art
                            }
                    except Exception as e:
                        Log("Failed to load pl_infojson '{}': {}".format(pl_infojson, e))

        # Process metadata for each episode
        @parallelize
        def UpdateEpisodes():
            # Note: the order of items in media.seasons is not always the same.
            for season_num in media.seasons:
                for episode_num in media.seasons[season_num].episodes:
                    episode_media = media.seasons[season_num].episodes[episode_num]
                    episode = metadata.seasons[season_num].episodes[episode_num]

                    try:
                        episode_file = episode_media.items[0].parts[0].file
                        if not episode_file:
                            continue
                        filepath_no_ext, _ = os.path.splitext(episode_file)
                    except Exception as e:
                        Log("Couldn't get file path for episode {}x{}: {}".format(season_num, episode_num, e))
                        continue

                    Log("Processing episode file: '{}'".format(episode_file))

                    # Try loading metadata from .info.json file yt-dlp stores
                    infojson = filepath_no_ext + ".info.json"
                    episode.title = PTN_TITLE.sub('', os.path.basename(filepath_no_ext)).strip()
                    if os.path.isfile(infojson):
                        try:
                            with open(infojson, encoding="utf-8") as f:
                                data = json.load(f)

                                # show-level metadata
                                metadict.setdefault("title", data.get("playlist_title", "Untitled"))
                                metadict.setdefault("summary", data.get("playlist_title", ""))
                                metadict.setdefault("studio", data.get("uploader", ""))
                                metadict.setdefault("genres", data.get("categories", []))

                                # episode-level metadata
                                episode.title = data.get('fulltitle', episode.title)
                                episode.summary = data.get("description", "")
                                episode.duration = int(data.get("duration", "0")) or None
                                if 'upload_date' in data:
                                    episode.originally_available_at = Datetime.ParseDate(data['upload_date']).date()
                                # episode.directors - not supported
                                # episode.writers - not supported

                                # TODO: use data.age_limit as metadata.content_rating?

                                # TODO: episode.absolute_index - data.playlist_index is not an absolute index
                                # if 'playlist_index' in data:
                                #     episode.absolute_index = data['playlist_index']

                                # TODO: episode.rating - related json data fields: like_count, dislike_count, average_rating
                                # if 'average_rating' in data:
                                #     episode.rating = (data['average_rating'] * 2)

                                Log("Successfully processed episode: {}".format(episode.title))
                        except Exception as e:
                            Log("Failed to load metadata for '{}': {}".format(infojson, e))
                    else:
                        Log("Missing .info.json file: '{}'".format(infojson))

                    # Check if there is a thumbnail for this episode
                    for ext in [".jpg", ".jpeg", ".webp", ".png", ".tiff", ".gif", ".jp2"]:
                        thumb_file = filepath_no_ext + ext
                        if os.path.isfile(thumb_file):
                            Log("Found thumbnail {}".format(thumb_file))
                            # we found an image, attempt to create an Proxy Media object to store it
                            try:
                                thumb_data = Core.storage.load(thumb_file)
                                thumb_hash = hashlib.md5(thumb_data).hexdigest()
                                episode.thumbs[thumb_hash] = Proxy.Media(thumb_data, sort_order=1)
                                episode.thumbs.validate_keys([thumb_hash])
                                Log("Thumbnail added for '{}': {}".format(episode.title, thumb_file))
                                break
                            except Exception as e:
                                Log("Error loading thumbnail '{}': {}".format(thumb_file, e))

        # metadict to metadata
        for k, v in metadict.items():
            setattr(metadata, k, v)

        Log("======== UPDATE END ========")
