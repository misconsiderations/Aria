#!/usr/bin/env python3
"""
One-shot conversion of legacy ```| X |\nY``` codeblock messages
to > **[icon] X** :: Y Discord quote/bold format.
"""
import re

INPUT = "main.py"
BACKUP = "main.py.bak_conversion"

with open(INPUT, "r", encoding="utf-8") as f:
    src = f.read()

# Make a backup
with open(BACKUP, "w", encoding="utf-8") as f:
    f.write(src)
print(f"Backup written to {BACKUP}")

# ── MANUAL targeted replacements ────────────────────────────────────────────
# Ordered list of (old, new) tuples — most specific first.

replacements = [

    # ── Spam ─────────────────────────────────────────────────────────────────
    (
        'f"```| Spam |\\nUsage: {bot.prefix}spam <count> <message>```"',
        'f"> **Spam** :: Usage: {bot.prefix}spam <count> <message>"',
    ),

    # ── Purge already running ────────────────────────────────────────────────
    (
        'f"```| Purge |\\nAlready running. Use {bot.prefix}spurge to stop.```"',
        'f"> **✗ Purge** :: Already running. Use {bot.prefix}spurge to stop."',
    ),

    # ── Mass DM ──────────────────────────────────────────────────────────────
    (
        'f"```| Mass DM |\\nUsage: {bot.prefix}massdm <1|2|3> <message>\\n1 = DM history  2 = Friends  3 = Both```"',
        'f"> **Mass DM** :: Usage: {bot.prefix}massdm <1|2|3> <message> — 1=DM history  2=Friends  3=Both"',
    ),
    (
        'f"```| Mass DM |\\nMessage is empty after plain-text cleanup```"',
        '"> **✗ Mass DM** :: Message is empty after plain-text cleanup"',
    ),
    (
        '"```| Mass DM |\\nInvalid option. Use 1, 2, or 3```"',
        '"> **✗ Mass DM** :: Invalid option. Use 1, 2, or 3"',
    ),
    (
        '"```| Mass DM |\\nFailed to fetch DMs```"',
        '"> **✗ Mass DM** :: Failed to fetch DMs"',
    ),
    (
        '"```| Mass DM |\\nNo targets found```"',
        '"> **✗ Mass DM** :: No targets found"',
    ),
    (
        'f"```| Mass DM |\\nMode: {option_names[option]}\\nTargets: {total}\\nStatus: Starting\\nSent: 0/{total}\\nFailed: 0```"',
        'f"> **Mass DM** :: Mode: {option_names[option]} · Targets: {total} · Status: Starting · Sent: 0/{total} · Failed: 0"',
    ),
    (
        'f"```| Mass DM |\\nMode: {option_names[option]}\\nTargets: {total}\\nStatus: Sending\\nSent: {sent}/{total}\\nFailed: {failed}\\nCurrent: {username}```"',
        'f"> **Mass DM** :: Mode: {option_names[option]} · Sent: {sent}/{total} · Failed: {failed} · Sending: {username}"',
    ),
    (
        'f"```| Mass DM |\\nMode: {option_names[option]}\\nSent: {sent}/{total}\\nFailed: {failed}\\nTime: {time.strftime(\'%H:%M:%S\')}```"',
        'f"> **✓ Mass DM** :: Mode: {option_names[option]} · Sent: {sent}/{total} · Failed: {failed} · Time: {time.strftime(\'%H:%M:%S\')}"',
    ),

    # ── Join ─────────────────────────────────────────────────────────────────
    (
        '"```| Join |\\nUsage: join <invite_code_or_url>```"',
        'f"> **Join** :: Usage: {bot.prefix}join <invite_code_or_url>"',
    ),

    # ── Auto Delete remaining usages ─────────────────────────────────────────
    (
        '"```| Auto Delete |\\nUsage: autodelete delay <seconds>```"',
        'f"> **Auto Delete** :: Usage: {bot.prefix}autodelete delay <seconds>"',
    ),
    (
        '"```| Auto Delete |\\nUsage: autodelete on/off | autodelete delay <seconds>```"',
        'f"> **Auto Delete** :: Usage: {bot.prefix}autodelete on/off | {bot.prefix}autodelete delay <seconds>"',
    ),

    # ── Server Load error ─────────────────────────────────────────────────────
    (
        'f"```| Server Load |\\nError: {str(e)}```"',
        'f"> **✗ Server Load** :: Error: {str(e)}"',
    ),

    # ── RPC ──────────────────────────────────────────────────────────────────
    (
        'msg_text = "```| RPC |\\nInvalid input```"',
        'msg_text = "> **✗ RPC** :: Invalid input"',
    ),

    # Crunchyroll RPC success (2 variants - check the actual text in file)
    (
        '"```| Crunchyroll RPC |\\n"',
        '"| Crunchyroll RPC |\\n"',  # placeholder - leave crunchyroll as-is since it's pass
    ),

    # Spotify RPC success (multi-field builder — refactor completely)
    (
        'msg_text = f"```| Spotify RPC |\\nsong={details}\\nartist={state}\\nalbum={name}\\nelapsed_minutes={elapsed_val}```"\n                    if total_val is not None:\n                        msg_text = msg_text.replace("```", f"\\ntotal_minutes={total_val}```")\n                    if image_url:\n                        msg_text = msg_text.replace("```", f"\\nimage_url=yes```")',
        '_sp_fields = [f"song={details}", f"artist={state}", f"album={name}", f"elapsed={elapsed_val}min"]\n                    if total_val is not None: _sp_fields.append(f"total={total_val}min")\n                    if image_url: _sp_fields.append("image=yes")\n                    msg_text = "> **✓ Spotify RPC** :: " + " · ".join(_sp_fields)',
    ),
    (
        '(\n                        "```| Spotify RPC |\\n"\n                        "Format: song=<name> artist=<name> album=<name> elapsed_minutes=<n> [total_minutes=<n>] [image_url=<url>]\\n"\n                        f"Example: {bot.prefix}rpc spotify song=Blinding_Lights artist=The_Weeknd album=After_Hours elapsed_minutes=1.5 total_minutes=3.5 image_url=https://image.url"\n                        "```"\n                    )',
        'f"> **Spotify RPC** :: Format: song=<name> artist=<name> album=<name> elapsed_minutes=<n> [total_minutes=<n>] [image_url=<url>] — Example: {bot.prefix}rpc spotify song=Blinding_Lights artist=The_Weeknd album=After_Hours elapsed_minutes=1.5 total_minutes=3.5"',
    ),
    (
        'msg_text = f"```| Spotify RPC |\\nError: {str(e)}```"',
        'msg_text = f"> **✗ Spotify RPC** :: Error: {str(e)}"',
    ),

    # YouTube RPC success
    (
        'msg_text = f"```| YouTube RPC |\\ntitle={details}\\nchannel={state}\\nelapsed_minutes={elapsed_val}```"\n                    if total_val is not None:\n                        msg_text = msg_text.replace("```", f"\\ntotal_minutes={total_val}```")\n                    if button_label:\n                        msg_text = msg_text.replace("```", f"\\nbutton={button_label}```")\n                    if image_url:\n                        msg_text = msg_text.replace("```", f"\\nimage_url=yes```")',
        '_yt_fields = [f"title={details}", f"channel={state}", f"elapsed={elapsed_val}min"]\n                    if total_val is not None: _yt_fields.append(f"total={total_val}min")\n                    if button_label: _yt_fields.append(f"button={button_label}")\n                    if image_url: _yt_fields.append("image=yes")\n                    msg_text = "> **✓ YouTube RPC** :: " + " · ".join(_yt_fields)',
    ),
    (
        '(\n                        "```| YouTube RPC |\\n"\n                        "Format: title=<name> channel=<name> elapsed_minutes=<n> [total_minutes=<n>] [image_url=<url>] [>> Button >> URL]\\n"\n                        f"Example: {bot.prefix}rpc youtube title=Devlog_12 channel=Aria_Channel elapsed_minutes=2.5 total_minutes=10 image_url=https://image.url >> Watch >> https://youtube.com"\n                        "```"\n                    )',
        'f"> **YouTube RPC** :: Format: title=<name> channel=<name> elapsed_minutes=<n> [total_minutes=<n>] [image_url=<url>] [>> Button >> URL] — Example: {bot.prefix}rpc youtube title=Devlog_12 channel=Aria_Channel elapsed_minutes=2.5"',
    ),
    (
        'msg_text = f"```| YouTube RPC |\\nError: {str(e)}```"',
        'msg_text = f"> **✗ YouTube RPC** :: Error: {str(e)}"',
    ),

    # SoundCloud RPC success
    (
        'msg_text = f"```| SoundCloud RPC |\\ntrack={details}\\nartist={state}\\nelapsed_minutes={elapsed_val}```"\n                    if total_val is not None:\n                        msg_text = msg_text.replace("```", f"\\ntotal_minutes={total_val}```")\n                    if button_label:\n                        msg_text = msg_text.replace("```", f"\\nbutton={button_label}```")\n                    if image_url:\n                        msg_text = msg_text.replace("```", f"\\nimage_url=yes```")',
        '_sc_fields = [f"track={details}", f"artist={state}", f"elapsed={elapsed_val}min"]\n                    if total_val is not None: _sc_fields.append(f"total={total_val}min")\n                    if button_label: _sc_fields.append(f"button={button_label}")\n                    if image_url: _sc_fields.append("image=yes")\n                    msg_text = "> **✓ SoundCloud RPC** :: " + " · ".join(_sc_fields)',
    ),
    (
        '(\n                        "```| SoundCloud RPC |\\n"\n                        "Format: track=<name> artist=<name> elapsed_minutes=<n> [total_minutes=<n>] [image_url=<url>] [>> Button >> URL]\\n"\n                        f"Example: {bot.prefix}rpc soundcloud track=Track_Name artist=Artist_Name elapsed_minutes=1.2 total_minutes=4.1 image_url=https://image.url >> Listen >> https://soundcloud.com"\n                        "```"\n                    )',
        'f"> **SoundCloud RPC** :: Format: track=<name> artist=<name> elapsed_minutes=<n> [total_minutes=<n>] [image_url=<url>] — Example: {bot.prefix}rpc soundcloud track=Track_Name artist=Artist_Name elapsed_minutes=1.2"',
    ),
    (
        'msg_text = f"```| SoundCloud RPC |\\nError: {str(e)}```"',
        'msg_text = f"> **✗ SoundCloud RPC** :: Error: {str(e)}"',
    ),

    # Generic App RPC success
    (
        'msg_text = f"```| {app_label} RPC |\\ntitle={details}\\ncontext={state}\\nelapsed_minutes={elapsed_val}```"\n                    if total_val is not None:\n                        msg_text = msg_text.replace("```", f"\\ntotal_minutes={total_val}```")\n                    if button_label:\n                        msg_text = msg_text.replace("```", f"\\nbutton={button_label}```")\n                    if image_url:\n                        msg_text = msg_text.replace("```", f"\\nimage_url=yes```")',
        '_app_fields = [f"title={details}", f"context={state}", f"elapsed={elapsed_val}min"]\n                    if total_val is not None: _app_fields.append(f"total={total_val}min")\n                    if button_label: _app_fields.append(f"button={button_label}")\n                    if image_url: _app_fields.append("image=yes")\n                    msg_text = f"> **✓ {app_label} RPC** :: " + " · ".join(_app_fields)',
    ),
    (
        '(\n                        f"```| {app_label} RPC |\\n"\n                        "Format: title=<name> context=<name> elapsed_minutes=<n> [total_minutes=<n>] [image_url=<url>] [>> Button >> URL]\\n"\n                        f"Example: {bot.prefix}rpc {parts} title=Title_Here context=Context_Here elapsed_minutes=3.5 total_minutes=22 image_url=https://image.url >> Open >> https://example.com"\n                        "```"\n                    )',
        'f"> **{app_label} RPC** :: Format: title=<name> context=<name> elapsed_minutes=<n> [total_minutes=<n>] [image_url=<url>] — Example: {bot.prefix}rpc {parts} title=Title_Here context=Context_Here elapsed_minutes=3.5"',
    ),
    (
        'msg_text = f"```| RPC |\\nError ({parts}): {str(e)}```"',
        'msg_text = f"> **✗ RPC** :: Error ({parts}): {str(e)}"',
    ),

    # Listening RPC
    (
        'msg_text = f"```| Listening RPC |\\nname={name}```"\n                    if details:\n                        msg_text = msg_text.replace("```", f"\\ndetails={details}```")\n                    if state:\n                        msg_text = msg_text.replace("```", f"\\nstate={state}```")\n                    if button_label:\n                        msg_text = msg_text.replace("```", f"\\nbutton={button_label}```")\n                    if image_url:\n                        msg_text = msg_text.replace("```", f"\\nimage_url=yes```")',
        '_li_fields = [f"name={name}"]\n                    if details: _li_fields.append(f"details={details}")\n                    if state: _li_fields.append(f"state={state}")\n                    if button_label: _li_fields.append(f"button={button_label}")\n                    if image_url: _li_fields.append("image=yes")\n                    msg_text = "> **✓ Listening RPC** :: " + " · ".join(_li_fields)',
    ),
    (
        'msg_text = f"```| Listening RPC |\\nFormat: name=<name> [details=<text>] [state=<text>] [image_url=<url>] [>> Button >> URL]\\nExample: {bot.prefix}rpc listening name=Spotify details=Playing_playlist state=15_tracks image_url=https://image.url >> Listen_Now >> https://spotify.com```"',
        'msg_text = f"> **Listening RPC** :: Format: name=<name> [details=<text>] [state=<text>] [image_url=<url>] [>> Button >> URL] — Example: {bot.prefix}rpc listening name=Spotify"',
    ),
    (
        'msg_text = f"```| Listening RPC |\\nError: {str(e)}```"',
        'msg_text = f"> **✗ Listening RPC** :: Error: {str(e)}"',
    ),

    # Streaming RPC
    (
        'msg_text = f"```| Streaming RPC |\\nname={name}```"\n                    if details:\n                        msg_text = msg_text.replace("```", f"\\ndetails={details}```")\n                    if state:\n                        msg_text = msg_text.replace("```", f"\\nstate={state}```")\n                    if button_label:\n                        msg_text = msg_text.replace("```", f"\\nbutton={button_label}```")\n                    if image_url:\n                        msg_text = msg_text.replace("```", f"\\nimage_url=yes```")',
        '_st_fields = [f"name={name}"]\n                    if details: _st_fields.append(f"details={details}")\n                    if state: _st_fields.append(f"state={state}")\n                    if button_label: _st_fields.append(f"button={button_label}")\n                    if image_url: _st_fields.append("image=yes")\n                    msg_text = "> **✓ Streaming RPC** :: " + " · ".join(_st_fields)',
    ),
    (
        'msg_text = f"```| Streaming RPC |\\nFormat: name=<name> [details=<text>] [state=<text>] [image_url=<url>] [>> Button >> URL]\\nExample: {bot.prefix}rpc streaming name=Twitch details=Playing_GTA_V state=In_session image_url=https://image.url >> Watch_Live >> https://twitch.tv```"',
        'msg_text = f"> **Streaming RPC** :: Format: name=<name> [details=<text>] [state=<text>] [image_url=<url>] [>> Button >> URL] — Example: {bot.prefix}rpc streaming name=Twitch"',
    ),
    (
        'msg_text = f"```| Streaming RPC |\\nError: {str(e)}```"',
        'msg_text = f"> **✗ Streaming RPC** :: Error: {str(e)}"',
    ),

    # Playing RPC
    (
        'msg_text = f"```| Playing RPC |\\nname={name}```"\n                    if details:\n                        msg_text = msg_text.replace("```", f"\\ndetails={details}```")\n                    if state:\n                        msg_text = msg_text.replace("```", f"\\nstate={state}```")\n                    if button_label:\n                        msg_text = msg_text.replace("```", f"\\nbutton={button_label}```")\n                    if image_url:\n                        msg_text = msg_text.replace("```", f"\\nimage_url=yes```")',
        '_pl_fields = [f"name={name}"]\n                    if details: _pl_fields.append(f"details={details}")\n                    if state: _pl_fields.append(f"state={state}")\n                    if button_label: _pl_fields.append(f"button={button_label}")\n                    if image_url: _pl_fields.append("image=yes")\n                    msg_text = "> **✓ Playing RPC** :: " + " · ".join(_pl_fields)',
    ),
    (
        'msg_text = f"```| Playing RPC |\\nFormat: name=<name> [details=<text>] [state=<text>] [image_url=<url>]\\nExample: {bot.prefix}rpc playing name=World_of_Warcraft details=Level_85 state=Questing image_url=https://image.url```"',
        'msg_text = f"> **Playing RPC** :: Format: name=<name> [details=<text>] [state=<text>] [image_url=<url>] — Example: {bot.prefix}rpc playing name=World_of_Warcraft"',
    ),
    (
        'msg_text = f"```| Playing RPC |\\nError: {str(e)}```"',
        'msg_text = f"> **✗ Playing RPC** :: Error: {str(e)}"',
    ),

    # Timer RPC success
    (
        'msg_text = f"```| Timer RPC |\\nname={name}\\nduration_minutes={duration_min}```"\n                    if details:\n                        msg_text = msg_text.replace("```", f"\\ndetails={details}```")\n                    if state:\n                        msg_text = msg_text.replace("```", f"\\nstate={state}```")\n                    if image_url:\n                        msg_text = msg_text.replace("```", f"\\nimage_url=yes```")',
        '_tm_fields = [f"name={name}", f"duration={duration_min}min"]\n                    if details: _tm_fields.append(f"details={details}")\n                    if state: _tm_fields.append(f"state={state}")\n                    if image_url: _tm_fields.append("image=yes")\n                    msg_text = "> **✓ Timer RPC** :: " + " · ".join(_tm_fields)',
    ),
    (
        'msg_text = f"```| Timer RPC |\\nFormat: name=<name> details=<text> state=<text> start=<unix> end=<unix> [image_url=<url>]\\nExample: {bot.prefix}rpc timer name=Gym details=Workout_session state=45_min_left start=1700000000 end=1700003600 image_url=https://image.url```"',
        'msg_text = f"> **Timer RPC** :: Format: name=<name> details=<text> state=<text> start=<unix> end=<unix> [image_url=<url>] — Example: {bot.prefix}rpc timer name=Gym details=Workout_session"',
    ),
    (
        'msg_text = f"```| Timer RPC |\\nError: {str(e)}```"',
        'msg_text = f"> **✗ Timer RPC** :: Error: {str(e)}"',
    ),

    # RPC invalid type
    (
        'msg_text = "```| RPC |\\nInvalid type. Use: " + ", ".join(valid_types) + "```"',
        'msg_text = "> **✗ RPC** :: Invalid type. Use: " + ", ".join(valid_types)',
    ),

    # ── Set Server Banner ────────────────────────────────────────────────────
    (
        'f"```| Set Server Banner |\\nUsage: {bot.prefix}setserverbanner <image_url>\\n(Nitro required for server banners)```"',
        'f"> **Set Server Banner** :: Usage: {bot.prefix}setserverbanner <image_url> (Nitro required)"',
    ),
    (
        '"```| Set Server Banner |\\nMust be used in a server```"',
        '"> **✗ Set Server Banner** :: Must be used in a server"',
    ),
    (
        'f"```| Set Server Banner |\\nFailed to download image (HTTP {r.status_code})```"',
        'f"> **✗ Set Server Banner** :: Failed to download image (HTTP {r.status_code})"',
    ),
    (
        '"```| Set Server Banner |\\nServer banner updated```"',
        '"> **✓ Set Server Banner** :: Server banner updated"',
    ),
    (
        'f"```| Set Server Banner |\\nFailed: HTTP {code}{\' — \' + err if err else \'\'}\\n(Nitro required for server banners)```"',
        'f"> **✗ Set Server Banner** :: Failed: HTTP {code}{\' — \' + err if err else \'\'} (Nitro required)"',
    ),
    (
        'f"```| Set Server Banner |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Set Server Banner** :: Error: {str(e)[:80]}"',
    ),

    # ── Steal Server Banner usage ─────────────────────────────────────────────
    (
        'f"```| Steal Server Banner |\\nUsage: {bot.prefix}stealserverbanner <user_id|@mention>\\nSteals their server-specific banner and sets it as YOUR server banner in this server```")',
        'f"> **Steal Server Banner** :: Usage: {bot.prefix}stealserverbanner <user_id|@mention>")',
    ),

    # ── Steal Server Nick usage ───────────────────────────────────────────────
    (
        'f"```| Steal Server Nick |\\nUsage: {bot.prefix}stealservernick <user_id|@mention>\\nSteals their server nickname and sets it as YOUR nickname in this server```")',
        'f"> **Steal Server Nick** :: Usage: {bot.prefix}stealservernick <user_id|@mention>")',
    ),

    # ── Steal Server Icon usage ───────────────────────────────────────────────
    (
        'f"```| Steal Server Icon |\\nUsage: {bot.prefix}stealservericon [guild_id]\\nSteals the server\'s icon and sets it as YOUR global avatar\\n(no guild_id needed when used inside the server)```")',
        'f"> **Steal Server Icon** :: Usage: {bot.prefix}stealservericon [guild_id] — no guild_id needed when run in the server")',
    ),

    # ── Mimic ────────────────────────────────────────────────────────────────
    (
        'f"```| Mimic |\\nUsage: {bot.prefix}mimic <@user|user_id> [custom reply]\\nUse {bot.prefix}stopmock to stop\\nOr: {bot.prefix}mimic <text> for one-off echo```"',
        'f"> **Mimic** :: Usage: {bot.prefix}mimic <@user|user_id> [custom reply] — Use {bot.prefix}stopmock to stop"',
    ),
    (
        '"```| Mimic |\\nYou cannot mimic yourself or a bot```"',
        '"> **✗ Mimic** :: You cannot mimic yourself or a bot"',
    ),

    # ── Antinuke usage (only one not yet converted) ───────────────────────────
    (
        'f"```| Antinuke |\\n{p}antinuke on|off|status|settings\\n{p}antinuke actions [add|remove|list] <warn|kick|ban>```"',
        'f"> **Antinuke** :: Usage: {p}antinuke on|off|status|settings — {p}antinuke actions [add|remove|list] <warn|kick|ban>"',
    ),

    # ── Autobump ─────────────────────────────────────────────────────────────
    (
        '"```| Autobump |\\n+bump config <channel_id> <interval_seconds>\\n+bump list\\n+bump stop```"',
        'f"> **Autobump** :: Usage: {bot.prefix}bump config <channel_id> <interval_seconds> | {bot.prefix}bump list | {bot.prefix}bump stop"',
    ),
    (
        '"```| Autobump |\\nUsage: +bump config <channel_id> <interval_seconds>```"',
        'f"> **Autobump** :: Usage: {bot.prefix}bump config <channel_id> <interval_seconds>"',
    ),
    (
        '"```| Autobump |\\nInterval must be at least 300 seconds (5 minutes)```"',
        '"> **✗ Autobump** :: Interval must be at least 300 seconds (5 minutes)"',
    ),
    (
        '"```| Autobump |\\nInterval must be a number (seconds)```"',
        '"> **✗ Autobump** :: Interval must be a number (seconds)"',
    ),
    (
        'f"```| Autobump |\\nConfigured: Channel {channel_id}, Interval {interval}s```"',
        'f"> **✓ Autobump** :: Configured — Channel {channel_id} · Interval {interval}s"',
    ),
    (
        'f"```| Autobump Config |\\nChannel: {cfg[\'channel_id\']}\\nInterval: {cfg[\'interval\']}s```"',
        'f"> **Autobump Config** :: Channel {cfg[\'channel_id\']} · Interval {cfg[\'interval\']}s"',
    ),
    (
        '"```| Autobump |\\nNo autobump configured```"',
        '"> **Autobump** :: No autobump configured"',
    ),

    # ── Admin ─────────────────────────────────────────────────────────────────
    (
        'f"```| Admin |\\nUsage:\\n{bot.prefix}admin add <user_id>\\n{bot.prefix}admin remove <user_id>\\n{bot.prefix}admin list```"',
        'f"> **Admin** :: Usage: {bot.prefix}admin add <user_id> | {bot.prefix}admin remove <user_id> | {bot.prefix}admin list"',
    ),
    (
        'f"```| Admin |\\nAdded admin: {uid}```"',
        'f"> **✓ Admin** :: Added admin: {uid}"',
    ),
    (
        'f"```| Admin |\\nRemoved admin: {uid}```"',
        'f"> **✓ Admin** :: Removed admin: {uid}"',
    ),
    (
        'f"```| Admin |\\nTotal: {len(entries)}\\n{body}```"',
        'f"> **Admin** :: Total: {len(entries)}\\n{body}"',
    ),
    (
        'f"```| Admin |\\nUsage: add/remove/list```"',
        '"> **Admin** :: Usage: add/remove/list"',
    ),

    # ── Auth ──────────────────────────────────────────────────────────────────
    (
        'f"```| Auth |\\nUsage: {p}auth <user_id>   — grant user website/dashboard access\\n       {p}unauth <user_id> — revoke site access\\n       {p}authlist       — list authed users```")',
        'f"> **Auth** :: Usage: {p}auth <user_id> — grant access | {p}unauth <user_id> — revoke | {p}authlist — list")',
    ),
    (
        'f"```| Auth |\\n✓ User {uid} granted website/dashboard access```"',
        'f"> **✓ Auth** :: User {uid} granted website/dashboard access"',
    ),
    (
        'f"```| Unauth |\\nUsage: {bot.prefix}unauth <user_id>```"',
        'f"> **Unauth** :: Usage: {bot.prefix}unauth <user_id>"',
    ),
    (
        'f"```| Auth |\\n✓ User {uid} revoked```"',
        'f"> **✓ Unauth** :: User {uid} revoked"',
    ),

    # ── Whitelist ─────────────────────────────────────────────────────────────
    (
        'f"```| Whitelist |\\nUsage:\\n{bot.prefix}whitelist add <user_id>\\n{bot.prefix}whitelist remove <user_id>\\n{bot.prefix}whitelist list```"',
        'f"> **Whitelist** :: Usage: {bot.prefix}whitelist add <user_id> | {bot.prefix}whitelist remove <user_id> | {bot.prefix}whitelist list"',
    ),
    (
        'f"```| Whitelist |\\n✓ {uid} site access restored```"',
        'f"> **✓ Whitelist** :: {uid} site access restored"',
    ),
    (
        'f"```| Whitelist |\\nRemoved {uid}```"',
        'f"> **✓ Whitelist** :: Removed {uid}"',
    ),
    (
        'f"```| Whitelist |\\nTotal: {len(lines)}\\n{body}```"',
        'f"> **Whitelist** :: Total: {len(lines)}\\n{body}"',
    ),
    (
        'f"```| Whitelist |\\nUsage: add/remove/list```"',
        '"> **Whitelist** :: Usage: add/remove/list"',
    ),

    # ── Blacklist ─────────────────────────────────────────────────────────────
    (
        'f"```| Blacklist |\\nUsage:\\n{bot.prefix}blacklist add <user_id>\\n{bot.prefix}blacklist remove <user_id>\\n{bot.prefix}blacklist list```"',
        'f"> **Blacklist** :: Usage: {bot.prefix}blacklist add <user_id> | {bot.prefix}blacklist remove <user_id> | {bot.prefix}blacklist list"',
    ),
    (
        'f"```| Blacklist |\\n✗ {uid} site access revoked{stopped_note}```"',
        'f"> **✗ Blacklist** :: {uid} site access revoked{stopped_note}"',
    ),
    (
        'f"```| Blacklist |\\nUnblocked {uid}```"',
        'f"> **✓ Blacklist** :: Unblocked {uid}"',
    ),
    (
        'f"```| Blacklist |\\nTotal: {len(lines)}\\n{body}```"',
        'f"> **Blacklist** :: Total: {len(lines)}\\n{body}"',
    ),
    (
        'f"```| Blacklist |\\nUsage: add/remove/list```"',
        '"> **Blacklist** :: Usage: add/remove/list"',
    ),

    # ── Host ──────────────────────────────────────────────────────────────────
    (
        '"```| Host |\\nUnavailable on hosted instances```"',
        '"> **✗ Host** :: Unavailable on hosted instances"',
    ),
    (
        'f"```| Host |\\nRate limited. Wait {remaining}s before hosting again```"',
        'f"> **✗ Host** :: Rate limited. Wait {remaining}s before hosting again"',
    ),
    (
        '"```| Host |\\nYou are blocked from hosting. Contact @misconsiderations```"',
        '"> **✗ Host** :: You are blocked from hosting. Contact @misconsiderations"',
    ),
    (
        'f"```| Host |\\nUsage: {bot.prefix}host <token> [prefix]\\nExample: {bot.prefix}host mfa.xxxxxx ;```"',
        'f"> **Host** :: Usage: {bot.prefix}host <token> [prefix] — Example: {bot.prefix}host mfa.xxxxxx ;"',
    ),
    (
        'f"```| Host |\\nToken check failed: {str(e)[:80]}```"',
        'f"> **✗ Host** :: Token check failed: {str(e)[:80]}"',
    ),
    (
        '"```| Host |\\nInvalid token```"',
        '"> **✗ Host** :: Invalid token"',
    ),
    (
        'f"```| Host |\\nAlready hosted — {hosted_username} ({hosted_user_id})\\n✓ Dashboard access granted```"',
        'f"> **Host** :: Already hosted — {hosted_username} ({hosted_user_id}) · Dashboard access granted"',
    ),
    (
        'f"```| Host |\\n{detail}```"',
        'f"> **✗ Host** :: {detail}"',
    ),
    (
        'f"```| Host |\\nHosted: {hosted_username} ({hosted_user_id})\\nUID: {hosted_uid}\\nPrefix: {prefix}```"',
        'f"> **✓ Host** :: Hosted: {hosted_username} ({hosted_user_id}) · UID: {hosted_uid} · Prefix: {prefix}"',
    ),

    # ── Hosted rate limit ─────────────────────────────────────────────────────
    (
        'f"```| Hosted |\\nRate limited. Wait {remaining}s before listing again```"',
        'f"> **✗ Hosted** :: Rate limited. Wait {remaining}s before listing again"',
    ),

    # ── Hosted Logs ───────────────────────────────────────────────────────────
    (
        'f"```| Hosted Logs |\\nUsage: {bot.prefix}hostedlogs <uid> [lines=50]```")',
        'f"> **Hosted Logs** :: Usage: {bot.prefix}hostedlogs <uid> [lines=50]")',
    ),
    (
        'f"```| Hosted Logs |\\nNo log found for uid: {uid}```")',
        'f"> **✗ Hosted Logs** :: No log found for uid: {uid}")',
    ),
    (
        'f"```| Hosted Logs [{uid}] (last {len(tail)} lines) |\\n{content}```")',
        'f"> **Hosted Logs** :: [{uid}] last {len(tail)} lines:\\n{content}")',
    ),
    (
        'f"```| Hosted Logs |\\nError reading log: {str(e)[:80]}```")',
        'f"> **✗ Hosted Logs** :: Error reading log: {str(e)[:80]}")',
    ),

    # ── Clear/Stop/Restart All Hosted ─────────────────────────────────────────
    (
        'f"```| Clear All Hosted |\\nRemoved {removed} entries```"',
        'f"> **✓ Clear All Hosted** :: Removed {removed} entries"',
    ),
    (
        'f"```| Stop All Hosted |\\nStopped {stopped} running instance{\'s\' if stopped != 1 else \'\'}```"',
        'f"> **✓ Stop All Hosted** :: Stopped {stopped} running instance{\'s\' if stopped != 1 else \'\'}"',
    ),
    (
        'f"```| Restart All Hosted |\\nRestarted {restarted} hosted instance{\'s\' if restarted != 1 else \'\'}```"',
        'f"> **✓ Restart All Hosted** :: Restarted {restarted} hosted instance{\'s\' if restarted != 1 else \'\'}"',
    ),
    (
        'f"```| Clear Host |\\nRate limited. Wait {remaining}s before removing hosted entries again```"',
        'f"> **✗ Clear Host** :: Rate limited. Wait {remaining}s before removing hosted entries again"',
    ),
    (
        'f"```| Clear Host |\\nRemoved {removed} entr{\'y\' if removed == 1 else \'ies\'}```"',
        'f"> **✓ Clear Host** :: Removed {removed} entr{\'y\' if removed == 1 else \'ies\'}"',
    ),

    # ── Back Token ────────────────────────────────────────────────────────────
    (
        'f"```| Back Token |\\nRate limited. Wait {remaining}s before requesting another token```"',
        'f"> **✗ Back Token** :: Rate limited. Wait {remaining}s before requesting another token"',
    ),
    (
        'f"```| Back Token |\\nUsage: {bot.prefix}backtoken <user_id>\\nReturns the stored bot token for a hosted user.```"',
        'f"> **Back Token** :: Usage: {bot.prefix}backtoken <user_id> — Returns the stored bot token for a hosted user"',
    ),
    (
        'f"```| Back Token |\\nNo hosted entry found for user_id {target_uid}```"',
        'f"> **✗ Back Token** :: No hosted entry found for user_id {target_uid}"',
    ),
    (
        'f"```| Back Token |\\nUser: {username} ({target_uid})\\nToken: {token}```"',
        'f"> **✓ Back Token** :: User: {username} ({target_uid}) · Token: {token}"',
    ),

    # ── Validate Hosted ───────────────────────────────────────────────────────
    (
        'f"```| Validate Hosted |\\nRate limited. Wait {remaining}s before validating again```"',
        'f"> **✗ Validate Hosted** :: Rate limited. Wait {remaining}s before validating again"',
    ),
    (
        '"```| Validate Hosted |\\nAll hosted tokens for your account appear valid```"',
        '"> **✓ Validate Hosted** :: All hosted tokens for your account appear valid"',
    ),
    (
        '"```| Validate Hosted |\\nRemoved invalid hosted entries:\\n" + "\\n".join(lines) + "```"',
        '"> **✓ Validate Hosted** :: Removed invalid hosted entries:\\n" + "\\n".join(lines)',
    ),

    # ── Backup ────────────────────────────────────────────────────────────────
    (
        'f"```| Backup |\\n✓ User backup complete\\nFile: {filename}```"',
        'f"> **✓ Backup** :: User backup complete · File: {filename}"',
    ),
    (
        'f"```| Backup |\\n✓ Message backup complete\\nFile: {filename}\\nMessages: {limit}```"',
        'f"> **✓ Backup** :: Message backup complete · File: {filename} · Messages: {limit}"',
    ),
    (
        'f"```| Backup |\\n✓ Full backup complete\\nFile: {filename}```"',
        'f"> **✓ Backup** :: Full backup complete · File: {filename}"',
    ),
    (
        'f"```| Backup List |\\n{backup_list}\\n\\nTotal: {len(backups)} backups```"',
        'f"> **Backup List** :: Total: {len(backups)} backups\\n{backup_list}"',
    ),
    (
        '"```| Backup |\\nNo backups found```"',
        '"> **Backup** :: No backups found"',
    ),
    (
        'f"```| Backup |\\n✓ Restored from {backup_name}```"',
        'f"> **✓ Backup** :: Restored from {backup_name}"',
    ),
    (
        'f"```| Backup |\\n✗ Backup not found: {backup_name}```"',
        'f"> **✗ Backup** :: Backup not found: {backup_name}"',
    ),

    # ── Moderation ────────────────────────────────────────────────────────────
    (
        '"```| Moderation |\\n✗ This command only works in servers```"',
        '"> **✗ Moderation** :: This command only works in servers"',
    ),
    (
        '"```| Moderation |\\n✗ No valid user IDs provided```"',
        '"> **✗ Moderation** :: No valid user IDs provided"',
    ),
    (
        'f"```| Moderation |\\n✓ Kicked {count}/{len(user_ids)} users```"',
        'f"> **✓ Moderation** :: Kicked {count}/{len(user_ids)} users"',
    ),
    (
        'f"```| Moderation |\\n✓ Banned {count}/{len(user_ids)} users\\nDelete days: {delete_days}```"',
        'f"> **✓ Moderation** :: Banned {count}/{len(user_ids)} users · Delete days: {delete_days}"',
    ),
    (
        'f"```| Moderation |\\n✓ Added {count} words to filter```"',
        'f"> **✓ Moderation** :: Added {count} words to filter"',
    ),
    (
        'f"```| Moderation |\\n✗ Filter matched: {match}```"',
        'f"> **✗ Moderation** :: Filter matched: {match}"',
    ),
    (
        '"```| Moderation |\\n✓ No filter matches```"',
        '"> **✓ Moderation** :: No filter matches"',
    ),
    (
        'f"```| Moderation |\\n✓ Deleted {count}/{len(channel_ids)} channels```"',
        'f"> **✓ Moderation** :: Deleted {count}/{len(channel_ids)} channels"',
    ),
    (
        'f"```| Moderation |\\n✓ Deleted {count}/{len(role_ids)} roles```"',
        'f"> **✓ Moderation** :: Deleted {count}/{len(role_ids)} roles"',
    ),
    (
        'f"```| Moderation |\\nMembers: {len(members)}/{limit}\\nUse IDs for kick/ban commands```"',
        'f"> **Moderation** :: Members: {len(members)}/{limit} — Use IDs for kick/ban commands"',
    ),
    (
        'f"```| Moderation |\\nChannels: {len(channels)}\\n{channel_list}\\n{\'...\' if len(channels) > 15 else \'\'}```"',
        'f"> **Moderation** :: Channels: {len(channels)}\\n{channel_list}"',
    ),
    (
        'f"```| Moderation |\\nRoles: {len(roles)}\\n{role_list}\\n{\'...\' if len(roles) > 15 else \'\'}```"',
        'f"> **Moderation** :: Roles: {len(roles)}\\n{role_list}"',
    ),

    # ── AFK Notice ────────────────────────────────────────────────────────────
    (
        'f"```| AFK Notice |\\n{notice}```"',
        'f"> **AFK Notice** :: {notice}"',
    ),

    # ── User/Server History ───────────────────────────────────────────────────
    (
        'f"```| User History |\\nNo history found for user {user_id}```"',
        'f"> **User History** :: No history found for user {user_id}"',
    ),
    (
        'f"```| Server History |\\nNo history found for server {server_id}```"',
        'f"> **Server History** :: No history found for server {server_id}"',
    ),

    # ── Profile/Server Scraped ────────────────────────────────────────────────
    (
        'f"```| Profile Scraped |\\nUser: {profile_data.get(\'username\', \'Unknown\')}\\nStatus: ✓ Success```"',
        'f"> **✓ Profile Scraped** :: {profile_data.get(\'username\', \'Unknown\')}"',
    ),
    (
        'f"```| Profile Scrape Failed |\\nUser ID: {user_id}\\nStatus: ✗ Failed```"',
        'f"> **✗ Profile Scrape** :: Failed for user_id {user_id}"',
    ),
    (
        'f"```| Server Scraped |\\nServer: {server_data.get(\'name\', \'Unknown\')}\\nStatus: ✓ Success```"',
        'f"> **✓ Server Scraped** :: {server_data.get(\'name\', \'Unknown\')}"',
    ),
    (
        'f"```| Server Scrape Failed |\\nServer ID: {server_id}\\nStatus: ✗ Failed```"',
        'f"> **✗ Server Scrape** :: Failed for server_id {server_id}"',
    ),
    (
        '"```| Mass Scraping |\\nStarting data collection...```"',
        '"> **Mass Scraping** :: Starting data collection..."',
    ),
    (
        'f"```| Mass Scraping Complete |\\nServers: {servers_scraped}\\nUsers: {users_scraped}\\nStatus: ✓ Complete```"',
        'f"> **✓ Mass Scraping** :: Servers: {servers_scraped} · Users: {users_scraped} · Complete"',
    ),
    (
        'f"```| Users Queued |\\nAdded {queued_count} users to scrape queue\\nTotal queued: {len(history_manager.get_users_to_scrape())}```"',
        'f"> **✓ Users Queued** :: Added {queued_count} users · Total queued: {len(history_manager.get_users_to_scrape())}"',
    ),
    (
        '"```| Scrape Queue |\\nNo users queued for scraping```"',
        '"> **Scrape Queue** :: No users queued for scraping"',
    ),
    (
        '"```| Processing Queue |\\nStarting profile scraping...```"',
        '"> **Processing Queue** :: Starting profile scraping..."',
    ),
    (
        'f"```| Queue Processed |\\nRemaining in queue: {queued_remaining}\\nStatus: ✓ Complete```"',
        'f"> **✓ Queue Processed** :: Remaining in queue: {queued_remaining}"',
    ),
    (
        'f"```| User Changes |\\nNo changes found for user {user_id}```"',
        'f"> **User Changes** :: No changes found for user {user_id}"',
    ),
    (
        'f"```| Server Changes |\\nNo changes found for server {server_id}```"',
        'f"> **Server Changes** :: No changes found for server {server_id}"',
    ),

    # ── Local Stats ───────────────────────────────────────────────────────────
    (
        'f"```| Local Stats |\\nStatus: {status}\\nLast Run: {time.strftime(\'%Y-%m-%d %H:%M:%S\', time.localtime(captured_at))}\\nGuild Count: {guilds.get(\'count\', 0)}\\nOwned Guilds: {guilds.get(\'owned_count\', 0)}\\nAdmin Guilds: {guilds.get(\'admin_count\', 0)}\\nHas Nitro: {\'Yes\' if account.get(\'premium_type\') else \'No\'}\\nTop Features: {feature_text}```"',
        'f"> **Local Stats** :: {status} · Guilds: {guilds.get(\'count\', 0)} owned={guilds.get(\'owned_count\', 0)} admin={guilds.get(\'admin_count\', 0)} · Nitro: {\'Yes\' if account.get(\'premium_type\') else \'No\'} · Last Run: {time.strftime(\'%H:%M:%S\', time.localtime(captured_at))}"',
    ),
    (
        'f"```| Local Stats |\\nRefreshed at: {time.strftime(\'%Y-%m-%d %H:%M:%S\', time.localtime(summary[\'captured_at\']))}\\nGuild Count: {summary[\'guilds\'][\'count\']}\\nStatus: ✓ Saved to account_stats.json```"',
        'f"> **✓ Local Stats** :: Refreshed · Guilds: {summary[\'guilds\'][\'count\']} · Saved to account_stats.json"',
    ),
    (
        'f"```| Local Stats |\\n{message}```"',
        'f"> **Local Stats** :: {message}"',
    ),
    (
        'f"```| Local Stats Status |\\nActive: {\'Yes\' if status[\'active\'] else \'No\'}\\nInterval: {status[\'interval_seconds\']}s\\nLast Run: {last_run_text}```"',
        'f"> **Local Stats Status** :: Active: {\'Yes\' if status[\'active\'] else \'No\'} · Interval: {status[\'interval_seconds\']}s · Last Run: {last_run_text}"',
    ),
    (
        '"```| Local Stats |\\nUsage: +localstats [run|start <seconds>|stop|status]```"',
        'f"> **Local Stats** :: Usage: {bot.prefix}localstats [run|start <seconds>|stop|status]"',
    ),

    # ── Export Commands ───────────────────────────────────────────────────────
    # The big help text block — preserve as multi-line but without codeblock
    (
        '"```| Export Commands |\\nexport account :: Export current account profile\\nexport guilds :: Export current guild list\\nexport friends :: Export current relationships\\nexport dms :: Export DM channel summaries\\nexport summary :: Export the latest non-sensitive local summary\\nexport all :: Export all supported runtime datasets\\nexport auto start [target] [seconds] :: Start background auto scrape\\nexport auto stop :: Stop background auto scrape\\nexport auto status :: Show background auto scrape status\\nexport auto run [target] :: Run one immediate background scrape cycle\\n\\nManual exports write JSON under ./exports. Auto scrape stores rolling snapshots in account_stats.json\\n```"',
        'f"> **Export** :: export account|guilds|friends|dms|summary|all | export auto start [target] [seconds] | export auto stop|status|run [target]"',
    ),
    (
        'f"```| Export Auto Scrape |\\nActive: {\'Yes\' if status[\'active\'] else \'No\'}\\nInterval: {status[\'interval_seconds\']}s\\nTargets: {targets_text}\\nLast Run: {last_run_text}```"',
        'f"> **Export Auto Scrape** :: Active: {\'Yes\' if status[\'active\'] else \'No\'} · Interval: {status[\'interval_seconds\']}s · Targets: {targets_text} · Last Run: {last_run_text}"',
    ),
    (
        'f"```| Export Auto Scrape |\\n{message}```"',
        'f"> **Export Auto Scrape** :: {message}"',
    ),
    (
        'f"```| Export Auto Scrape |\\nRan immediate scrape\\nTargets: {targets_text}\\nCaptured At: {time.strftime(\'%Y-%m-%d %H:%M:%S\', time.localtime(snapshot[\'captured_at\']))}```"',
        'f"> **✓ Export Auto Scrape** :: Ran immediate scrape · Targets: {targets_text}"',
    ),
    (
        '"```| Export Auto Scrape |\\nUsage: +export auto [status|start [target] [seconds]|stop|run [target]]```"',
        'f"> **Export Auto Scrape** :: Usage: {bot.prefix}export auto [status|start [target] [seconds]|stop|run [target]]"',
    ),
    (
        'f"```| Export |\\nFetching real-time {target} data...```"',
        'f"> **Export** :: Fetching real-time {target} data..."',
    ),
    (
        'f"```| Export Complete |\\nTarget: {target}\\nFile: {file_path}{detail_block}\\nStatus: ✓ Success```"',
        'f"> **✓ Export** :: {target} → {file_path}{detail_block}"',
    ),
    (
        'f"```| Export Failed |\\nTarget: {target}\\nError: {message}```"',
        'f"> **✗ Export** :: {target} failed — {message}"',
    ),
    (
        '"```| Background Scrape Summary |\\nNo automatic scrape snapshot available yet\\nUse +export auto run all or wait for the background cycle```"',
        'f"> **Background Scrape Summary** :: No snapshot available yet — use {bot.prefix}export auto run all"',
    ),

    # ── Badge ─────────────────────────────────────────────────────────────────
    (
        'f"```| Badge Decode |\\nFlags: {args[1]}\\nBadges: {badge_text}```"',
        'f"> **Badge Decode** :: Flags: {args[1]} · Badges: {badge_text}"',
    ),
    (
        'f"```| Badge Scraper |\\nInvalid user ID: {user_id}```"',
        'f"> **✗ Badge Scraper** :: Invalid user ID: {user_id}"',
    ),
    (
        'f"```| User Badges |\\nUser: {record.get(\'username\', \'Unknown\')}#{record.get(\'discriminator\', \'0000\')}\\nID: {record.get(\'user_id\')}\\nFlags: {record.get(\'public_flags\', 0)}\\nBadges: {badge_text}```"',
        'f"> **User Badges** :: {record.get(\'username\', \'Unknown\')}#{record.get(\'discriminator\', \'0000\')} ({record.get(\'user_id\')}) · Flags: {record.get(\'public_flags\', 0)} · {badge_text}"',
    ),
    (
        'f"```| Badge Scraper |\\nScraping badges from server {server_id}\\nLimit: {limit}```"',
        'f"> **Badge Scraper** :: Scraping server {server_id} (limit {limit})..."',
    ),
    (
        '"```| Badge Commands |\\nInvalid command. Use +badges for help```"',
        'f"> **✗ Badge** :: Invalid command. Use {bot.prefix}badges for help"',
    ),

    # ── Join Invite ───────────────────────────────────────────────────────────
    (
        'f"```| Join Invite |\\nUsage: {bot.prefix}joininvite <invite_code>\\nExamples:\\n  {bot.prefix}ji abc123\\n  {bot.prefix}ji discord.gg/abc123```"',
        'f"> **Join Invite** :: Usage: {bot.prefix}joininvite <invite_code> — Example: {bot.prefix}ji abc123"',
    ),
    (
        'f"```| Join Invite |\\nJoining {invite_code}...```"',
        'f"> **Join Invite** :: Joining {invite_code}..."',
    ),
    (
        'f"```| Join Invite |\\n{result}```")',
        'f"> **✓ Join Invite** :: {result}")',
    ),
    (
        'f"```| Join Invite |\\nFailed: {err_msg}```")',
        'f"> **✗ Join Invite** :: Failed: {err_msg}")',
    ),
    (
        'f"```| Join Invite |\\n{result_text}```")',
        'f"> **Join Invite** :: {result_text}")',
    ),

    # ── Leave Guild ───────────────────────────────────────────────────────────
    (
        'f"```| Leave Guild |\\nUsage: {bot.prefix}leaveguild <guild_id>```"',
        'f"> **Leave Guild** :: Usage: {bot.prefix}leaveguild <guild_id>"',
    ),
    (
        'f"```| Leave Guild |\\nLeft guild {guild_id}```"',
        'f"> **✓ Leave Guild** :: Left guild {guild_id}"',
    ),
    (
        'f"```| Leave Guild |\\nFailed ({r.status_code}): {err or \'Unknown error\'}```"',
        'f"> **✗ Leave Guild** :: Failed ({r.status_code}): {err or \'Unknown error\'}"',
    ),
    (
        'f"```| Leave Guild |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Leave Guild** :: Error: {str(e)[:80]}"',
    ),

    # ── Check Token ───────────────────────────────────────────────────────────
    (
        'f"```| Check Token |\\nUsage: {bot.prefix}checktoken <token>```"',
        'f"> **Check Token** :: Usage: {bot.prefix}checktoken <token>"',
    ),
    (
        'f"```| Token Valid |\\nUser: {username} ({user_id})\\nEmail: {email}\\nNitro: {nitro}\\nPhone: {phone}\\nMFA: {mfa}```"',
        'f"> **✓ Token Valid** :: {username} ({user_id}) · Email: {email} · Nitro: {nitro} · MFA: {mfa}"',
    ),
    (
        '"```| Check Token |\\nInvalid token (401 Unauthorized)```"',
        '"> **✗ Check Token** :: Invalid token (401 Unauthorized)"',
    ),
    (
        'f"```| Check Token |\\nUnexpected response: HTTP {r.status_code}```"',
        'f"> **✗ Check Token** :: Unexpected response: HTTP {r.status_code}"',
    ),
    (
        'f"```| Check Token |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Check Token** :: Error: {str(e)[:80]}"',
    ),

    # ── My Guilds ─────────────────────────────────────────────────────────────
    (
        'f"```| My Guilds |\\nFailed: HTTP {r.status_code if r else \'no response\'}```"',
        'f"> **✗ My Guilds** :: Failed: HTTP {r.status_code if r else \'no response\'}"',
    ),
    (
        'f"```| My Guilds |\\nError: {str(e)[:80]}```"',
        'f"> **✗ My Guilds** :: Error: {str(e)[:80]}"',
    ),

    # ── Host Blacklist ────────────────────────────────────────────────────────
    (
        'f"```| Host Blacklist |\\n{bot.prefix}hostblacklist add <user_id> :: Block a user from hosting\\n{bot.prefix}hostblacklist remove <user_id> :: Unblock a user\\n{bot.prefix}hostblacklist list :: Show all blacklisted users```"',
        'f"> **Host Blacklist** :: {bot.prefix}hostblacklist add <user_id> | remove <user_id> | list"',
    ),
    (
        'f"```| Host Blacklist |\\nBlacklisted user {uid}```"',
        'f"> **✓ Host Blacklist** :: Blacklisted user {uid}"',
    ),
    (
        'f"```| Host Blacklist |\\nRemoved {uid} from blacklist```"',
        'f"> **✓ Host Blacklist** :: Removed {uid} from blacklist"',
    ),
    (
        'f"```| Host Blacklist |\\n{uid} is not blacklisted```"',
        'f"> **Host Blacklist** :: {uid} is not blacklisted"',
    ),
    (
        '"```| Host Blacklist |\\nNo blacklisted users```"',
        '"> **Host Blacklist** :: No blacklisted users"',
    ),
    (
        '"```| Host Blacklist |\\nUsage: add/remove/list```"',
        '"> **Host Blacklist** :: Usage: add/remove/list"',
    ),

    # ── User Info ─────────────────────────────────────────────────────────────
    (
        'f"```| User Info |\\nUser not found: {uid}```"',
        'f"> **✗ User Info** :: User not found: {uid}"',
    ),
    (
        'f"```| User Info |\\nError: {str(e)[:80]}```"',
        'f"> **✗ User Info** :: Error: {str(e)[:80]}"',
    ),

    # ── Mass Leave ───────────────────────────────────────────────────────────
    (
        'f"```| Mass Leave |\\nFailed to fetch guilds: HTTP {r.status_code if r else \'no response\'}```")',
        'f"> **✗ Mass Leave** :: Failed to fetch guilds: HTTP {r.status_code if r else \'no response\'}")',
    ),
    (
        '"```| Mass Leave |\\nNo eligible guilds to leave```")',
        '"> **✗ Mass Leave** :: No eligible guilds to leave")',
    ),
    (
        'f"```| Mass Leave |\\nLeaving {len(targets)} guild(s)...```")',
        'f"> **Mass Leave** :: Leaving {len(targets)} guild(s)...")',
    ),
    (
        'f"```| Mass Leave |\\nDone\\nLeft: {left} | Failed: {failed} | Owned (skipped): {len(all_guilds) - len(leavable)}```"',
        'f"> **✓ Mass Leave** :: Done · Left: {left} | Failed: {failed} | Owned skipped: {len(all_guilds) - len(leavable)}"',
    ),
    (
        'f"```| Mass Leave |\\nError: {str(e)[:80]}```")',
        'f"> **✗ Mass Leave** :: Error: {str(e)[:80]}")',
    ),

    # ── Guild Members ─────────────────────────────────────────────────────────
    (
        'f"```| Guild Members |\\nUsage: {bot.prefix}members <guild_id> [limit]```"',
        'f"> **Guild Members** :: Usage: {bot.prefix}members <guild_id> [limit]"',
    ),
    (
        'f"```| Guild Members |\\nFailed: HTTP {r.status_code if r else \'No response\'}\\n(Need GUILD_MEMBERS intent / admin access)```"',
        'f"> **✗ Guild Members** :: Failed: HTTP {r.status_code if r else \'No response\'} (need admin access)"',
    ),
    (
        'f"```| Guild Members |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Guild Members** :: Error: {str(e)[:80]}"',
    ),

    # ── Recent Messages ───────────────────────────────────────────────────────
    (
        '"```| Recent Messages |\\nDatabase not available```"',
        '"> **✗ Recent Messages** :: Database not available"',
    ),
    (
        'f"```| Recent Messages |\\n{no_msg_text}```"',
        'f"> **Recent Messages** :: {no_msg_text}"',
    ),
    (
        'f"```| Recent Messages |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Recent Messages** :: Error: {str(e)[:80]}"',
    ),

    # ── Friends ───────────────────────────────────────────────────────────────
    (
        'f"```| Friends |\\nFailed: HTTP {r.status_code}```"',
        'f"> **✗ Friends** :: Failed: HTTP {r.status_code}"',
    ),
    (
        'f"```| Friends |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Friends** :: Error: {str(e)[:80]}"',
    ),
    (
        'f"```| Friends |\\nFriend request sent to {target_id}```"',
        'f"> **✓ Friends** :: Friend request sent to {target_id}"',
    ),
    (
        'f"```| Friends |\\nFailed ({r.status_code}): {err or \'Unknown\'}```"',
        'f"> **✗ Friends** :: Failed ({r.status_code}): {err or \'Unknown\'}"',
    ),
    (
        'f"```| Friends |\\nRemoved {target_id}```"',
        'f"> **✓ Friends** :: Removed {target_id}"',
    ),
    (
        'f"```| Friends |\\nFailed: HTTP {r.status_code}```"',
        'f"> **✗ Friends** :: Failed: HTTP {r.status_code}"',
    ),
    (
        'f"```| Friends |\\nBlocked {target_id}```"',
        'f"> **✓ Friends** :: Blocked {target_id}"',
    ),
    (
        'f"```| Friends |\\n{bot.prefix}friends list [page]     — show friend list\\n{bot.prefix}friends add <id>         — send friend request\\n{bot.prefix}friends remove <id>      — remove friend\\n{bot.prefix}friends block <id>       — block user```"',
        'f"> **Friends** :: {bot.prefix}friends list [page] | {bot.prefix}friends add <id> | {bot.prefix}friends remove <id> | {bot.prefix}friends block <id>"',
    ),

    # ── DM User ───────────────────────────────────────────────────────────────
    (
        'f"```| DM User |\\nUsage: {bot.prefix}dmuser <user_id> <message...>```"',
        'f"> **DM User** :: Usage: {bot.prefix}dmuser <user_id> <message>"',
    ),
    (
        'f"```| DM User |\\nFailed to open DM: HTTP {code}```"',
        'f"> **✗ DM User** :: Failed to open DM: HTTP {code}"',
    ),
    (
        'f"```| DM User |\\nSent to {target_id}```"',
        'f"> **✓ DM User** :: Sent to {target_id}"',
    ),
    (
        '"```| DM User |\\nFailed to send message```"',
        '"> **✗ DM User** :: Failed to send message"',
    ),
    (
        'f"```| DM User |\\nError: {str(e)[:80]}```"',
        'f"> **✗ DM User** :: Error: {str(e)[:80]}"',
    ),

    # ── Delete History ────────────────────────────────────────────────────────
    (
        'f"```| Delete History |\\nScanning for your messages (limit {limit})...```"',
        'f"> **Delete History** :: Scanning for your messages (limit {limit})..."',
    ),
    (
        'f"```| Delete History |\\nDeleted {deleted} of your messages```"',
        'f"> **✓ Delete History** :: Deleted {deleted} of your messages"',
    ),
    (
        'f"```| Delete History |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Delete History** :: Error: {str(e)[:80]}"',
    ),

    # ── Snipe ─────────────────────────────────────────────────────────────────
    (
        '"```| Snipe |\\nNothing sniped in this channel yet```"',
        '"> **Snipe** :: Nothing sniped in this channel yet"',
    ),
    (
        'f"```| Snipe deleted at {deleted_str} |\\n{author} ({uid}){attach_str}:\\n{content}```"',
        'f"> **Snipe** :: Deleted at {deleted_str} — **{author}** ({uid}){attach_str}\\n> {content}"',
    ),

    # ── Edit Snipe ────────────────────────────────────────────────────────────
    (
        '"```| Edit Snipe |\\nNo edits sniped in this channel yet```"',
        '"> **Edit Snipe** :: No edits sniped in this channel yet"',
    ),
    (
        'f"```| Edit Snipe {author} ({uid}) at {edited_str} |\\nBefore\\n{before_c}\\nAfter \\n{after_c}```"',
        'f"> **Edit Snipe** :: **{author}** ({uid}) at {edited_str}\\n> Before: {before_c}\\n> After:  {after_c}"',
    ),

    # ── Invite Info ───────────────────────────────────────────────────────────
    (
        'f"```| Invite Info |\\nUsage: {bot.prefix}inviteinfo <code_or_url>```"',
        'f"> **Invite Info** :: Usage: {bot.prefix}inviteinfo <code_or_url>"',
    ),
    (
        '"```| Invite Info |\\nInvalid or expired invite```"',
        '"> **✗ Invite Info** :: Invalid or expired invite"',
    ),
    (
        'f"```| Invite Info |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Invite Info** :: Error: {str(e)[:80]}"',
    ),

    # ── Create Invite ─────────────────────────────────────────────────────────
    (
        'f"```| Create Invite |\\nFailed: HTTP {r.status_code if r else \'No response\'}```"',
        'f"> **✗ Create Invite** :: Failed: HTTP {r.status_code if r else \'No response\'}"',
    ),
    (
        'f"```| Create Invite |\\ndiscord.gg/{inv_code}\\nExpires: {age_str} | Uses: {uses_str}```"',
        'f"> **✓ Create Invite** :: discord.gg/{inv_code} · Expires: {age_str} · Uses: {uses_str}"',
    ),
    (
        'f"```| Create Invite |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Create Invite** :: Error: {str(e)[:80]}"',
    ),

    # ── Channel Info ──────────────────────────────────────────────────────────
    (
        'f"```| Channel Info |\\nFailed: HTTP {r.status_code if r else \'No response\'}```"',
        'f"> **✗ Channel Info** :: Failed: HTTP {r.status_code if r else \'No response\'}"',
    ),
    (
        'f"```| Channel Info |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Channel Info** :: Error: {str(e)[:80]}"',
    ),

    # ── Typing ────────────────────────────────────────────────────────────────
    (
        'f"```| Typing |\\nTyping in {channel_id} for {duration}s```"',
        'f"> **Typing** :: Typing in {channel_id} for {duration}s"',
    ),

    # ── Accept All ────────────────────────────────────────────────────────────
    (
        'f"```| Accept All |\\nFailed: HTTP {r.status_code}```"',
        'f"> **✗ Accept All** :: Failed: HTTP {r.status_code}"',
    ),
    (
        '"```| Accept All |\\nNo pending friend requests```"',
        '"> **Accept All** :: No pending friend requests"',
    ),
    (
        'f"```| Accept All |\\nAccepted: {accepted} | Failed: {failed} | Total: {len(incoming)}```"',
        'f"> **✓ Accept All** :: Accepted: {accepted} | Failed: {failed} | Total: {len(incoming)}"',
    ),
    (
        'f"```| Accept All |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Accept All** :: Error: {str(e)[:80]}"',
    ),

    # ── React ─────────────────────────────────────────────────────────────────
    (
        'f"```| React |\\nUsage: {bot.prefix}react <emoji>\\n       {bot.prefix}react <msg_id> <emoji>\\n       {bot.prefix}react <ch_id> <msg_id> <emoji>```"',
        'f"> **React** :: Usage: {bot.prefix}react <emoji> | {bot.prefix}react <msg_id> <emoji> | {bot.prefix}react <ch_id> <msg_id> <emoji>"',
    ),
    (
        '"```| React |\\nNo target message found```"',
        '"> **✗ React** :: No target message found"',
    ),
    (
        'f"```| React |\\nReacted {emoji}```"',
        'f"> **✓ React** :: Reacted {emoji}"',
    ),
    (
        'f"```| React |\\nFailed ({code}): {err or \'Unknown\'}```"',
        'f"> **✗ React** :: Failed ({code}): {err or \'Unknown\'}"',
    ),

    # ── Pin ───────────────────────────────────────────────────────────────────
    (
        '"```| Pin |\\nNo target message found```"',
        '"> **✗ Pin** :: No target message found"',
    ),
    (
        'f"```| Pin |\\nPinned {message_id}```"',
        'f"> **✓ Pin** :: Pinned {message_id}"',
    ),
    (
        'f"```| Pin |\\nFailed: HTTP {r.status_code if r else \'No response\'}```"',
        'f"> **✗ Pin** :: Failed: HTTP {r.status_code if r else \'No response\'}"',
    ),

    # ── Unpin ─────────────────────────────────────────────────────────────────
    (
        'f"```| Unpin |\\nUsage: {bot.prefix}unpin <message_id>```"',
        'f"> **Unpin** :: Usage: {bot.prefix}unpin <message_id>"',
    ),
    (
        'f"```| Unpin |\\nUnpinned {args[0]}```"',
        'f"> **✓ Unpin** :: Unpinned {args[0]}"',
    ),
    (
        'f"```| Unpin |\\nFailed: HTTP {r.status_code if r else \'No response\'}```"',
        'f"> **✗ Unpin** :: Failed: HTTP {r.status_code if r else \'No response\'}"',
    ),

    # ── Role Info ─────────────────────────────────────────────────────────────
    (
        'f"```| Role Info |\\nUsage: {bot.prefix}roleinfo <role_id>```"',
        'f"> **Role Info** :: Usage: {bot.prefix}roleinfo <role_id>"',
    ),
    (
        '"```| Role Info |\\nMust be used in a server```"',
        '"> **✗ Role Info** :: Must be used in a server"',
    ),
    (
        'f"```| Role Info |\\nFailed: HTTP {r.status_code if r else \'No response\'}```"',
        'f"> **✗ Role Info** :: Failed: HTTP {r.status_code if r else \'No response\'}"',
    ),
    (
        'f"```| Role Info |\\nRole {role_id} not found```"',
        'f"> **✗ Role Info** :: Role {role_id} not found"',
    ),
    (
        'f"```| Role Info |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Role Info** :: Error: {str(e)[:80]}"',
    ),

    # ── Steal Emoji ───────────────────────────────────────────────────────────
    (
        'f"```| Steal Emoji |\\nUsage: {bot.prefix}stealemoji <:name:id> [target_guild_id]```"',
        'f"> **Steal Emoji** :: Usage: {bot.prefix}stealemoji <:name:id> [target_guild_id]"',
    ),
    (
        '"```| Steal Emoji |\\nProvide target guild ID or run in a server```"',
        '"> **✗ Steal Emoji** :: Provide target guild ID or run in a server"',
    ),
    (
        '"```| Steal Emoji |\\nPaste as <:name:id>, <a:name:id>, or raw ID```"',
        '"> **✗ Steal Emoji** :: Paste as <:name:id>, <a:name:id>, or raw ID"',
    ),
    (
        'f"```| Steal Emoji |\\nFailed to download: HTTP {img_r.status_code}```"',
        'f"> **✗ Steal Emoji** :: Failed to download: HTTP {img_r.status_code}"',
    ),
    (
        'f"```| Steal Emoji |\\nAdded :{emoji_name}: (ID {new_id}) to {target_guild}```"',
        'f"> **✓ Steal Emoji** :: Added :{emoji_name}: (ID {new_id}) to {target_guild}"',
    ),
    (
        'f"```| Steal Emoji |\\nUpload failed ({upload_r.status_code}): {err or \'Unknown\'}```"',
        'f"> **✗ Steal Emoji** :: Upload failed ({upload_r.status_code}): {err or \'Unknown\'}"',
    ),
    (
        'f"```| Steal Emoji |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Steal Emoji** :: Error: {str(e)[:80]}"',
    ),

    # ── List Invites ──────────────────────────────────────────────────────────
    (
        'f"```| List Invites |\\nUsage: {bot.prefix}listinvites [guild_id]```"',
        'f"> **List Invites** :: Usage: {bot.prefix}listinvites [guild_id]"',
    ),
    (
        'f"```| List Invites |\\nFailed: HTTP {r.status_code if r else \'No response\'}```"',
        'f"> **✗ List Invites** :: Failed: HTTP {r.status_code if r else \'No response\'}"',
    ),
    (
        '"```| List Invites |\\nNo active invites```"',
        '"> **List Invites** :: No active invites"',
    ),
    (
        'f"```| List Invites |\\nError: {str(e)[:80]}```"',
        'f"> **✗ List Invites** :: Error: {str(e)[:80]}"',
    ),

    # ── Webhook ───────────────────────────────────────────────────────────────
    (
        'f"```| Webhook |\\nUsage: {bot.prefix}webhook <url> <message>\\n       {bot.prefix}webhook <url> --name <username> <message>```"',
        'f"> **Webhook** :: Usage: {bot.prefix}webhook <url> <message> [--name <username>]"',
    ),
    (
        '"```| Webhook |\\nInvalid webhook URL```"',
        '"> **✗ Webhook** :: Invalid webhook URL"',
    ),
    (
        '"```| Webhook |\\nMessage sent```"',
        '"> **✓ Webhook** :: Message sent"',
    ),
    (
        'f"```| Webhook |\\nFailed ({r.status_code}): {err or \'Unknown\'}```"',
        'f"> **✗ Webhook** :: Failed ({r.status_code}): {err or \'Unknown\'}"',
    ),
    (
        'f"```| Webhook |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Webhook** :: Error: {str(e)[:80]}"',
    ),

    # ── Reply ─────────────────────────────────────────────────────────────────
    (
        'f"```| Reply |\\nUsage: {bot.prefix}reply <message_id> <content...>```"',
        'f"> **Reply** :: Usage: {bot.prefix}reply <message_id> <content>"',
    ),
    (
        'f"```| Reply |\\nFailed: HTTP {code}```"',
        'f"> **✗ Reply** :: Failed: HTTP {code}"',
    ),
    (
        'f"```| Reply |\\nError: {str(e)[:80]}```"',
        'f"> **✗ Reply** :: Error: {str(e)[:80]}"',
    ),
]


def do_replace(text, old, new, label=""):
    count = text.count(old)
    if count == 0:
        print(f"  [SKIP] No match: {repr(old[:60])}")
        return text
    if count > 1:
        print(f"  [WARN] {count} matches for: {repr(old[:60])}")
    result = text.replace(old, new)
    print(f"  [OK]   {count} replacement(s): {repr(old[:60])}")
    return result


print(f"\nApplying {len(replacements)} replacements...")
changed = 0
for old, new in replacements:
    before = src
    src = do_replace(src, old, new)
    if src != before:
        changed += 1

print(f"\nDone: {changed}/{len(replacements)} replacements applied.")

with open(INPUT, "w", encoding="utf-8") as f:
    f.write(src)
print(f"Written to {INPUT}")
