import tornado.gen
import tornado.web

from common.web import requestsManager


class handler(requestsManager.asyncRequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.engine
    def asyncGet(self):
        self.add_header("Access-Control-Allow-Origin", "*")
        self.add_header("Content-Type", "application/json")
        self.write(r"{}")
        self.set_status(200)
