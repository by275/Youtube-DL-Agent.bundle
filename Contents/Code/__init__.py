#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
import os
import re
import urllib2

PTN_TITLE = re.compile(r'\[[a-zA-Z0-9_-]+\]')
PTN_NATSORT = re.compile('([0-9]+)')


def natural_sort_key(s):
    return [int(text) if text.isdigit() else text for text in PTN_NATSORT.split(str(s).lower())]

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
        infojson = os.path.splitext(media_file)[0].strip() + ".info.json" # little benefit of using pl_infojson
        if not os.path.isfile(infojson):
            return

        try:
            data = JSON.ObjectFromString(Core.storage.load(infojson))
            results.Append(MetadataSearchResult(
                id=data.get("playlist_id"),
                name=data.get("playlist_title", "") or media.title,
                year=data.get("upload_date", "")[:4] or None,
                lang=lang,
                score=100
            ))
            results.Sort('score', descending=True)
        except Exception as e:
            Log("Failed to get data from infojson: %s: %s", infojson, str(e))

        Log("======== SEARCH END ========")

    def update_episode_info(self, episode, basepath, showinfo):
        # Try loading metadata from .info.json file yt-dlp stores
        infojson = basepath + ".info.json"
        episode.title = PTN_TITLE.sub('', os.path.basename(basepath)).strip()
        if not os.path.isfile(infojson):
            Log("Missing .info.json file: %s", infojson)
            return

        try:
            data = JSON.ObjectFromString(Core.storage.load(infojson))

            # show-level metadata
            showinfo.setdefault("title", data.get("playlist_title", "Untitled"))
            showinfo.setdefault("summary", data.get("playlist_title", ""))
            showinfo.setdefault("studio", data.get("uploader", ""))
            showinfo.setdefault("genres", data.get("categories", []))

            # episode-level metadata
            episode.title = data.get('fulltitle', episode.title)
            episode.summary = data.get("description", "")
            episode.duration = int(data.get("duration", "0")) or None
            if 'upload_date' in data:
                # episode.originally_available_at = Datetime.ParseDate(data['upload_date']).date()
                # episode.originally_available_at = Datetime.FromTimestamp(int(data['timestamp'])+86400).date()
                episode.originally_available_at = (Datetime.ParseDate(data['upload_date']) + Datetime.Delta(days=1)).date()
            # episode.directors - not supported
            # episode.writers - not supported

            # TODO: use data.age_limit as metadata.content_rating?

            # TODO: episode.absolute_index - data.playlist_index is not an absolute index
            # if 'playlist_index' in data:
            #     episode.absolute_index = data['playlist_index']

            # TODO: episode.rating - related json data fields: like_count, dislike_count, average_rating
            # if 'average_rating' in data:
            #     episode.rating = (data['average_rating'] * 2)

            Log("Successfully updated episode info: %s", episode.title)
        except Exception as e:
            Log("Failed to get metadata from %s: %s", infojson, str(e))

    def update_episode_thumb(self, episode, basepath):
        # Check if there is a thumbnail for this episode
        for ext in [".jpg", ".jpeg", ".webp", ".png", ".tiff", ".gif", ".jp2"]:
            thumb_file = basepath + ext
            if not os.path.isfile(thumb_file):
                continue

            Log("Thumbnail found: %s", thumb_file)
            # we found an image, attempt to create an Proxy Media object to store it
            try:
                thumb_data = Core.storage.load(thumb_file)
                thumb_hash = hashlib.md5(thumb_data).hexdigest()
                if thumb_hash and thumb_hash not in episode.thumbs:
                    episode.thumbs[thumb_hash] = Proxy.Media(thumb_data, sort_order=1)
                    episode.thumbs.validate_keys([thumb_hash])
                    Log("Thumbnail added for %s: %s", episode.title, thumb_file)
                else:
                    Log("Thumbnail already added for %s", episode.title)
                return
            except Exception as e:
                Log("Error updating episode thumbnail %s: %s", thumb_file, str(e))

    def get_show_info(self, media):
        # show-level metadata from pl_infojson if possible
        file = ""
        for s in media.seasons if media else []:
            for e in media.seasons[s].episodes:
                file = media.seasons[s].episodes[e].items[0].parts[0].file
                if file:
                    break
        if not file:
            return

        dirname = os.path.dirname(file)
        filenames = ["", "playlist", os.path.basename(dirname)]
        filenames = [(f + ".info.json" if f else "info.json") for f in filenames]
        for filename in filenames:
            pl_infojson = os.path.join(dirname, filename)
            if not os.path.isfile(pl_infojson):
                continue
            try:
                data = JSON.ObjectFromString(Core.storage.load(pl_infojson))
                return {
                    "title": data["title"],
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
                Log("Failed to get data from pl_infojson: %s: %s", pl_infojson, str(e))

    def update(self, metadata, media, lang):
        Log("======== UPDATE START ========")

        # show-level metadata from pl_infojson if possible
        showinfo = self.get_show_info(media) or {}

        # Process metadata for each episode
        @parallelize
        def UpdateEpisodes():
            # Note: the order of items in media.seasons is not always the same.
            for season_num in sorted(media.seasons, key=natural_sort_key):
                for episode_num in sorted(media.seasons[season_num].episodes, key=natural_sort_key):
                    episode = metadata.seasons[season_num].episodes[episode_num]                    
                    try:
                        episode_media = media.seasons[season_num].episodes[episode_num]
                        episode_file = episode_media.items[0].parts[0].file
                        if not episode_file:
                            continue
                        filepath_no_ext, _ = os.path.splitext(episode_file)
                    except Exception as e:
                        Log("Couldn't get file path for episode %sx%s: %s", season_num, episode_num, str(e))
                        continue

                    Log("Processing episode file: %s", episode_file)

                    @task
                    def UpdateEpisode(episode=episode, basepath=filepath_no_ext):
                        self.update_episode_info(episode, basepath, showinfo)
                        self.update_episode_thumb(episode, basepath)

        # showinfo to metadata
        for k, v in showinfo.items():
            setattr(metadata, k, v)

        Log("======== UPDATE END ========")
