# ipop-project
# Copyright 2016, University of Florida
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

try:
    import simplejson as json
except ImportError:
    import json
import threading
from collections import defaultdict
import requests
from controller.framework.ControllerModule import ControllerModule


class OverlayVisualizer(ControllerModule):
    def __init__(self, cfx_handle, module_config, module_name):
        super(OverlayVisualizer, self).__init__(cfx_handle,
                                                module_config, module_name)
        # Visualizer webservice URL
        self.vis_address = "http://" + self._cm_config["WebServiceAddress"]
        self._vis_req_publisher = None
        self._ipop_version = self._cfx_handle.query_param("IpopVersion")

        # The visualizer dataset which is forwarded to the collector service
        self._vis_ds = dict(NodeId=self.node_id, VizData=defaultdict(dict))
        # Its lock
        self._vis_ds_lock = threading.Lock()

    def initialize(self):
        # We're using the pub-sub model here to gather data for the visualizer
        # from other modules
        # Using this publisher, the OverlayVisualizer publishes events in the
        # timer_method() and all subscribing modules are expected to reply
        # with the data they want to forward to the visualiser
        self._vis_req_publisher = \
            self._cfx_handle.publish_subscription("VIS_DATA_REQ")

        self.register_cbt("Logger", "LOG_INFO", "Module loaded")

    def process_cbt(self, cbt):
        if cbt.op_type == "Response":
            if cbt.request.action == "VIS_DATA_REQ":
                msg = cbt.response.data

                if cbt.response.status and msg:
                    with self._vis_ds_lock:
                        for mod_name in msg:
                            for ovrl_id in msg[mod_name]:
                                self._vis_ds["VizData"][ovrl_id][mod_name] = msg[mod_name][ovrl_id]
                else:
                    warn_msg = "Got no data in CBT response from module" \
                        " {}".format(cbt.request.recipient)
                    self.register_cbt("Logger", "LOG_WARNING", warn_msg)
                self.free_cbt(cbt)
            else:
                parent_cbt = cbt.parent
                cbt_data = cbt.response.data
                cbt_status = cbt.response.status
                self.free_cbt(cbt)
                if (parent_cbt is not None and parent_cbt.child_count == 1):
                    parent_cbt.set_response(cbt_data, cbt_status)
                    self.complete_cbt(parent_cbt)

        else:
            self.req_handler_default(cbt)

    def timer_method(self):
        with self._vis_ds_lock:
            vis_ds = self._vis_ds
            # flush old data, next itr provides new data
            self._vis_ds = dict(NodeId=self.node_id,
                                VizData=defaultdict(dict))
        if "NodeName" in self._cm_config:
            vis_ds["NodeName"] = self._cm_config["NodeName"]
        if "GeoCoordinate" in self._cm_config:
            vis_ds["GeoCoordinate"] = self._cm_config["GeoCoordinate"]
        vis_ds["IpopVersion"] = self._ipop_version
        self.log("LOG_DEBUG", "Submitted VizData=%s", vis_ds)
        req_url = "{}/IPOP/nodes/{}".format(self.vis_address, self.node_id)
        try:
            resp = requests.put(req_url,
                                data=json.dumps(vis_ds),
                                headers={"Content-Type": "application/json"},
                                timeout=3)
            resp.raise_for_status()
        except requests.exceptions.RequestException as err:
            err_msg = "Failed to send data to the IPOP Visualizer" \
                " webservice({0}). Exception: {1}" \
                .format(self.vis_address, str(err))
            self.register_cbt("Logger", "LOG_WARNING", err_msg)

        # Now that all the accumulated data has been dealt with, we request
        # more data
        self._vis_req_publisher.post_update(None)

    def terminate(self):
        pass
