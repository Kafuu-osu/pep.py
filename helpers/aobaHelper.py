from objects import glob

def getOsuVer(userID):
	"""
	Get `userID`'s osu! version.

	:param userID: user id
	:return: osu! version
	"""
	return glob.db.fetch("SELECT osuver FROM users WHERE id = %s LIMIT 1", [userID])["osuver"]