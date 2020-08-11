import sys
import time
import traceback

from common.constants import privileges
from common.log import logUtils as log
from common.ripple import userUtils
from constants import exceptions
from constants import serverPackets
from helpers import aobaHelper
from helpers import chatHelper as chat
from helpers import countryHelper
from helpers import locationHelper
from helpers import kotrikhelper
from objects import glob

import random





def handle(tornadoRequest):
    country=userID=osuVersion=requestIP = ""
    atitude=longitude = 0
    clientData = []
 
    # Data to return
    responseToken = None
    responseTokenString = "ayy"
    responseData = bytes()
 
    def saveLoginRecord(status, note=""):
        userUtils.saveLoginRecord(userID, osuVersion, requestIP, status, countryHelper.getCountryLetters(country), latitude, longitude, clientData=clientData, note=note)

    # Get IP from tornado request
    requestIP = tornadoRequest.getRequestIP()

    # Avoid exceptions
    clientData = ["unknown", "unknown", "unknown", "unknown", "unknown"]
    osuVersion = "unknown"

    # Split POST body so we can get username/password/hardware data
    # 2:-3 thing is because requestData has some escape stuff that we don't need
    loginData = str(tornadoRequest.request.body)[2:-3].split("\\n")
    try:
        # Make sure loginData is valid
        if len(loginData) < 3:
            raise exceptions.invalidArgumentsException()

        # Get HWID, MAC address and more
        # Structure (new line = "|", already split)
        # [0] osu! version
        # [1] plain mac addressed, separated by "."
        # [2] mac addresses hash set
        # [3] unique ID
        # [4] disk ID
        splitData = loginData[2].split("|")
        osuVersion = splitData[0]
        timeOffset = int(splitData[1])
        clientData = splitData[3].split(":")[:5]
        if len(clientData) < 4:
            raise exceptions.forceUpdateException()

        # Try to get the ID from username
        username = str(loginData[0])
        userID = userUtils.getID(username)

        if not userID:
            # Invalid username
            raise exceptions.loginFailedException()
        if not userUtils.checkLogin(userID, loginData[1]):
            # Invalid password
            raise exceptions.loginFailedException()

        # Make sure we are not banned or locked
        priv = userUtils.getPrivileges(userID)
        if userUtils.isBanned(userID) and priv & privileges.USER_PENDING_VERIFICATION == 0:
            raise exceptions.loginBannedException()
        if userUtils.isLocked(userID) and priv & privileges.USER_PENDING_VERIFICATION == 0:
            raise exceptions.loginLockedException()

        # 2FA check
        if userUtils.check2FA(userID, requestIP):
            log.warning("Need 2FA check for user {}".format(loginData[0]))
            raise exceptions.need2FAException()

        # No login errors!

        # Verify this user (if pending activation)
        firstLogin = False
        if priv & privileges.USER_PENDING_VERIFICATION > 0 or not userUtils.hasVerifiedHardware(userID):
            if userUtils.verifyUser(userID, clientData):
                # Valid account
                log.info("Account {} verified successfully!".format(userID))
                glob.verifiedCache[str(userID)] = 1
                firstLogin = True
            else:
                # Multiaccount detected
                log.info("Account {} NOT verified!".format(userID))
                glob.verifiedCache[str(userID)] = 0
                raise exceptions.loginBannedException()


        # Save HWID in db for multiaccount detection
        hwAllowed = userUtils.logHardware(userID, clientData, firstLogin)

        # This is false only if HWID is empty
        # if HWID is banned, we get restricted so there's no
        # need to deny bancho access
        if not hwAllowed:
            raise exceptions.haxException()

        # Log user IP
        userUtils.logIP(userID, requestIP)

        # Log user osuver
        kotrikhelper.setUserLastOsuVer(userID, osuVersion)
        log.info("User {}({}) login, client ver: {}, ip: {}".format(username, userID, osuVersion, requestIP))
  
  


        # Delete old tokens for that user and generate a new one
        isTournament = "tourney" in osuVersion
        if not isTournament:
            glob.tokens.deleteOldTokens(userID)
        responseToken = glob.tokens.addToken(userID, requestIP, timeOffset=timeOffset, tournament=isTournament)
        responseTokenString = responseToken.token

        # Check restricted mode (and eventually send message)
        responseToken.checkRestricted()

        # Send message if donor expires soon
        if responseToken.privileges & privileges.USER_DONOR > 0:
            responseToken.enqueue(serverPackets.notification("欢迎您，高贵的撒泼特"))
            #expireDate = userUtils.getDonorExpire(responseToken.userID)
            #if expireDate-int(time.time()) <= 86400*3:
            #    expireDays = round((expireDate-int(time.time()))/86400)
            #    expireIn = "{} days".format(expireDays) if expireDays > 1 else "less than 24 hours"
            #    responseToken.enqueue(serverPackets.notification("Your donor tag expires in {}! When your donor tag expires, you won't have any of the donor privileges, like yellow username, custom badge and discord custom role and username color! If you wish to keep supporting Ripple and you don't want to lose your donor privileges, you can donate again by clicking on 'Support us' on Ripple's website.".format(expireIn)))

        # Deprecate telegram 2fa and send alert
        if userUtils.deprecateTelegram2Fa(userID):
            responseToken.enqueue(serverPackets.notification("As stated on our blog, Telegram 2FA has been deprecated on 29th June 2018. Telegram 2FA has just been disabled from your account. If you want to keep your account secure with 2FA, please enable TOTP-based 2FA from our website https://ripple.moe. Thank you for your patience."))

        # Set silence end UNIX time in token
        responseToken.silenceEndTime = userUtils.getSilenceEnd(userID)

        # Get only silence remaining seconds
        silenceSeconds = responseToken.getSilenceSecondsLeft()

        # Get supporter/GMT
        userGMT = False
        if not userUtils.isRestricted(userID):
            userSupporter = True
        else:
            userSupporter = False
        userTournament = False
        if responseToken.admin:
            userGMT = True
        if responseToken.privileges & privileges.USER_TOURNAMENT_STAFF > 0:
            userTournament = True

        # Server restarting check
        if glob.restarting:
            raise exceptions.banchoRestartingException()

        # Send login notification before maintenance message
        loginNotification = glob.banchoConf.config["loginNotification"]


        #creating notification
        OnlineUsers = int(glob.redis.get("ripple:online_users").decode("utf-8"))
        Notif = "- Online Users: {}\n- {}".format(OnlineUsers, loginNotification) # - {random.choice(glob.banchoConf.config['Quotes'])}
        responseToken.enqueue(serverPackets.notification(Notif))

        # Maintenance check
        if glob.banchoConf.config["banchoMaintenance"]:
            if not userGMT:
                # We are not mod/admin, delete token, send notification and logout
                glob.tokens.deleteToken(responseTokenString)
                raise exceptions.banchoMaintenanceException()
            else:
                # We are mod/admin, send warning notification and continue
                responseToken.enqueue(serverPackets.notification("Bancho is in maintenance mode. Only mods/admins have full access to the server.\nType !system maintenance off in chat to turn off maintenance mode."))

        # BAN CUSTOM CHEAT CLIENTS
        # 0Ainu = First Ainu build
        # b20190326.2 = Ainu build 2 (MPGH PAGE 10)
        # b20190401.22f56c084ba339eefd9c7ca4335e246f80 = Ainu Aoba's Birthday Build
        # b20191223.3 = Unknown Ainu build? (Taken from most users osuver in cookiezi.pw)
        # b20190226.2 = hqOsu (hq-af)
        if True:
            # Ainu Client 2020 update
            if tornadoRequest.request.headers.get("ainu") == "happy":
                log.info(f"Account {userID} tried to use Ainu Client 2020!")
                if userUtils.isRestricted(userID):
                    responseToken.enqueue(serverPackets.notification("Ainu client... Really? Welp enjoy your ban! -Realistik"))
                else:
                    glob.tokens.deleteToken(userID)
                    userUtils.restrict(userID)
                    raise exceptions.loginCheatClientsException()
            # Ainu Client 2019
            elif aobaHelper.getOsuVer(userID) in ["0Ainu", "b20190326.2", "b20190401.22f56c084ba339eefd9c7ca4335e246f80", "b20191223.3"]:
                log.info(f"Account {userID} tried to use Ainu Client!")
                if userUtils.isRestricted(userID):
                    responseToken.enqueue(serverPackets.notification("Ainu client... Really? Welp enjoy your ban! -Realistik"))
                else:
                    glob.tokens.deleteToken(userID)
                    userUtils.restrict(userID)
                    raise exceptions.loginCheatClientsException()
            # hqOsu
            elif aobaHelper.getOsuVer(userID) == "b20190226.2":
                log.info(f"Account {userID} tried to use hqOsu!")
                if userUtils.isRestricted(userID):
                    responseToken.enqueue(serverPackets.notification("Trying to use hqOsu in here? Well... No, sorry. We don't allow cheats here. Go play on Aminosu."))
                else:
                    glob.tokens.deleteToken(userID)
                    userUtils.restrict(userID)
                    raise exceptions.loginCheatClientsException()
            
            #hqosu legacy
            elif aobaHelper.getOsuVer(userID) == "b20190716.5":
                log.info(f"Account {userID} tried to use hqOsu legacy!")
                if userUtils.isRestricted(userID):
                    responseToken.enqueue(serverPackets.notification("Trying to play with HQOsu Legacy? Cute..."))
                else:
                    glob.tokens.deleteToken(userID)
                    userUtils.restrict(userID)
                    raise exceptions.loginCheatClientsException()

        # Send all needed login packets
        responseToken.enqueue(serverPackets.silenceEndTime(silenceSeconds))
        responseToken.enqueue(serverPackets.userID(userID))
        responseToken.enqueue(serverPackets.protocolVersion())
        responseToken.enqueue(serverPackets.userSupporterGMT(userSupporter, userGMT, userTournament))
        responseToken.enqueue(serverPackets.userPanel(userID, True))
        responseToken.enqueue(serverPackets.userStats(userID, True))

        # Channel info end (before starting!?! wtf bancho?)
        responseToken.enqueue(serverPackets.channelInfoEnd())
        # Default opened channels
        # TODO: Configurable default channels
        chat.joinChannel(token=responseToken, channel="#osu")
        chat.joinChannel(token=responseToken, channel="#announce")

        # Join admin channel if we are an admin
        if responseToken.admin:
            chat.joinChannel(token=responseToken, channel="#admin")

        # Output channels info
        for key, value in glob.channels.channels.items():
            if value.publicRead and not value.hidden:
                responseToken.enqueue(serverPackets.channelInfo(key))

        # Send friends list
        responseToken.enqueue(serverPackets.friendList(userID))

        # Send main menu icon
        if glob.banchoConf.config["menuIcon"] != "":
            responseToken.enqueue(serverPackets.mainMenuIcon(glob.banchoConf.config["menuIcon"]))

        # Send online users' panels
        with glob.tokens:
            for _, token in glob.tokens.tokens.items():
                if not token.restricted:
                    responseToken.enqueue(serverPackets.userPanel(token.userID))

        # Get location and country from ip.zxq.co or database
        if glob.localize:
            # Get location and country from IP
            latitude, longitude = locationHelper.getLocation(requestIP)
            countryLetters = locationHelper.getCountry(requestIP)
            country = countryHelper.getCountryID(countryLetters)
        else:
            # Set location to 0,0 and get country from db
            log.warning("Location skipped")
            countryLetters = "XX"
            country = countryHelper.getCountryID(userUtils.getCountry(userID))
   
        saveLoginRecord("success")

        # Set location and country
        responseToken.setLocation(latitude, longitude)
        responseToken.country = country

        # Set country in db if user has no country (first bancho login)
        if userUtils.getCountry(userID) == "XX":
            userUtils.setCountry(userID, countryLetters)

        # Send to everyone our userpanel if we are not restricted or tournament
        if not responseToken.restricted:
            glob.streams.broadcast("main", serverPackets.userPanel(userID))

        # Set reponse data to right value and reset our queue
        responseData = responseToken.queue
        responseToken.resetQueue()
    except exceptions.loginFailedException:
        # Login failed error packet
        # (we don't use enqueue because we don't have a token since login has failed)
        responseData += serverPackets.loginFailed()
        saveLoginRecord("failed", note="Error packet")
    except exceptions.invalidArgumentsException:
        # Invalid POST data
        # (we don't use enqueue because we don't have a token since login has failed)
        responseData += serverPackets.loginFailed()
        responseData += serverPackets.notification("I see what you're doing...")
        saveLoginRecord("failed", note="Invalid POST data")
    except exceptions.loginBannedException:
        # Login banned error packet
        responseData += serverPackets.loginBanned()
        saveLoginRecord("failed", note="Banned")
    except exceptions.loginLockedException:
        # Login banned error packet
        responseData += serverPackets.loginLocked()
        saveLoginRecord("failed", note="Locked")
    except exceptions.loginCheatClientsException:
        # Banned for logging in with cheats
        responseData += serverPackets.loginCheats()
        saveLoginRecord("failed", note="Logging with cheats")
    except exceptions.banchoMaintenanceException:
        # Bancho is in maintenance mode
        responseData = bytes()
        if responseToken != None:
            responseData = responseToken.queue
        responseData += serverPackets.notification("Our bancho server is in maintenance mode. Please try to login again later.")
        responseData += serverPackets.loginFailed()
        saveLoginRecord("failed", note="Bancho is in maintenance mode")
    except exceptions.banchoRestartingException:
        # Bancho is restarting
        responseData += serverPackets.notification("Bancho is restarting. Try again in a few minutes.")
        responseData += serverPackets.loginFailed()
        saveLoginRecord("failed", note="Bancho is restarting")
    except exceptions.need2FAException:
        # User tried to log in from unknown IP
        responseData += serverPackets.needVerification()
        saveLoginRecord("failed", note="Need 2FA")
    except exceptions.forceUpdateException:
        # Using oldoldold client, we don't have client data. Force update.
        # (we don't use enqueue because we don't have a token since login has failed)
        responseData += serverPackets.forceUpdate()
        responseData += serverPackets.notification("Hory shitto, your client is TOO old! Nice prehistory! Please turn update it from the settings!")
        saveLoginRecord("failed", note="Too old client")
    except exceptions.haxException:
        responseData += serverPackets.notification("what")
        responseData += serverPackets.loginFailed()
        saveLoginRecord("failed", note="Not HWinfo")
    except:
        log.error("Unknown error!\n```\n{}\n{}```".format(sys.exc_info(), traceback.format_exc()))
        saveLoginRecord("failed", note="unknown error")
    finally:
        # Console and discord log
        if len(loginData) < 3:
            log.info("Invalid bancho login request from **{}** (insufficient POST data)".format(requestIP), "bunker")
            saveLoginRecord("failed", note="insufficient POST data")

        # Return token string and data
        return responseTokenString, responseData

