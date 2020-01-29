"""Simple implementation of wlformat.prov_exe schema using dicts
"""
from uuid import uuid1
import hashlib
from openalea.distributed.metadata.data_size import getsize


class Provenance(object):
    """Simple object to store provenance results
    """

    def __init__(self):
        print "constructor"
        self._uid = None
        self._data = []
        self._parameters = []
        self._executions = []

        self._workflow = None
        self.time_init = None
        self.time_end = None
        self._buffer = {}

    def workflow(self):
        """Returns id of associated workflow

        Notes: returns None is no workflow associated

        Returns:
            (str or None)
        """
        if self._workflow is None:
            return None

        return self._workflow.factory.uid

    def local_node_id(self, vid):
        """Return local index of node for current dataflow

        Warnings: used to go from dict based structure in openalea
                  to list based structure in wlformat

        Args:
            vid (int): id of vertex in dataflow

        Returns:
            (int): index of vertex in wlformat workflow
        """
        vids = sorted(self._workflow.vertices())
        vids = vids[2:]  # removed __in__ and __out__ port nodes
        return vids.index(vid)

    def last_execution(self, node_id):
        """Retrieve last execution of a given node

        Args:
            node_id (int): node index

        Returns:
            (dict)
        """
        for edef in reversed(self._executions):
            if edef['node'] == node_id:
                return edef

        return None

    def output_did(self, edef, port):
        """Retrieve id of data produced by a given port

        Args:
            edef (idct): an execution definition
            port (str): port name

        Returns:
            (str): id of data produced
        """
        for data in edef['outputs']:
            if data['port'] == port:
                return data['data']

        raise KeyError("unable to find '%s' for this execution" % port)

    def init(self, dataflow):
        """Initialize the provenance with a new dataflow

        Args:
            dataflow (CompositeNode): workflow currently under evaluation

        Returns:
            None
        """
        print "init prov", id(dataflow)
        self._uid = uuid1().hex
        self._workflow = dataflow
        self._buffer.clear()

    def before_eval(self, dataflow, vid):
        """Function called just before evaluating a node

        Args:
            dataflow (CompositeNode): workflow currently under evaluation
            vid (vid): id of node to be evaluated

        Returns:
            None
        """
        print "bef eval", id(dataflow), vid
        if vid in (0, 1):  # __in__ and __out__ fucking ports
            print "in out not handled"
            return

        node = dataflow.node(vid)

        # figure out what are the inputs
        in_port = {}
        for eid in dataflow.in_edges(vid):
            tid = dataflow.local_id(dataflow.target_port(eid))
            if tid in in_port:
                raise UserWarning("don't know how to handle multiple "
                                  "connection on same in port")
            in_port[tid] = dataflow.source_port(eid)

        inputs = []
        for i, port in enumerate(node.factory.inputs):
            if i in in_port:  # find id of data produced above
                oport = in_port[i]
                nid = self.local_node_id(dataflow.vertex(oport))
                last_exec = self.last_execution(nid)
                if last_exec is None:
                    raise UserWarning("something went wrong in the order "
                                      "of executions")
                fac = dataflow.node(dataflow.vertex(oport)).factory
                pname = fac.outputs[dataflow.local_id(oport)]['name']
                did = self.output_did(last_exec, pname)
            else:  # lonely input port
                did = set_id_parameter_data(dataflow, vid)
                data = dict(id=did,
                            type=str(port.get('interface')),
                            value=node.get_input(i),
                            size=getsize(node.get_input(i)))
                self._data.append(data)

                param = dict(node=self.local_node_id(vid),
                             port=port['name'],
                             data=did)
                self._parameters.append(param)

            inputs.append(dict(port=port['name'], 
                                data=did,
                                size=getsize(node.get_input(i))
                                ))

        self._buffer[vid] = inputs

    def after_eval(self, dataflow, vid, dt):
        """Function called just after evaluating a node

        Args:
            dataflow (CompositeNode): workflow currently under evaluation
            vid (vid): id of node to be evaluated
            dt: execution time of a task

        Returns:
            None
        """
        print "aft eval", id(dataflow), vid
        if vid in (0, 1):  # __in__ and __out__ fucking ports
            print "in out not handled"
            return

        node = dataflow.node(vid)
        # retrieve previously stored inputs
        inputs = self._buffer.pop(vid)

        # create a new data for each data on output port
        outputs = []
        for i, port in enumerate(node.factory.outputs):
            did = set_id_intermediate_data(inputs, dataflow, vid)
            outputs.append(dict(port=port['name'],
                                data=did,
                                size=getsize(node.get_output(i))))

            data = dict(id=did,
                        type=str(port.get('interface')),
                        # value=node.get_output(i),
                        size=getsize(node.get_output(i)))
            self._data.append(data)

        task_id = set_id_task(inputs, dataflow, vid)

        # create a new execution
        edef = dict(node=self.local_node_id(vid),
                    task_id=task_id,
                    # time_init=0,
                    # time_end=0,
                    cpu_time=dt,
                    n_input=len(inputs),
                    inputs=inputs,
                    n_output=len(outputs),
                    outputs=outputs)
        self._executions.append(edef)
        return edef

    def as_wlformat(self):
        """Convert this dictionary into a wlformat compatible dict

        Returns:
            (dict)
        """
        data = []
        for item in self._data:
            clone = dict(item)
            if clone['type'] == 'None':
                clone['value'] = None
            data.append(clone)

        pdef = dict(id=self._uid,
                    workflow=self._workflow.factory.uid,
                    time_init=self.time_init,
                    time_end=self.time_end,
                    data=data,
                    parameters=self._parameters,
                    executions=self._executions)
        return pdef


def set_id_task(inputs, dataflow, vid):
    """Get an uid for the task

    Returns:
        (str) : the id of the task
    """
    # generate an task uID based on the data id + node id
    # TODO: find a way to give an uid to the task - Now: the same as data
    node = dataflow.node(vid)
    tmp_did = ""
    for inp in inputs:
        tmp_did += inp['port'] + ":" + inp['data'] + ";"
    tmp_did += str(node.get_id())
    task_id = hashlib.sha224(tmp_did).hexdigest()

    return task_id

def set_id_intermediate_data(inputs, dataflow, vid):
    """Get an uid for the output data generated by task (vid)

    Returns:
        (str) : the id of the idata
    """
    node = dataflow.node(vid)
    did = ""
    for inp in inputs:
        did+=inp['port']+":"+inp['data']+";"
    did += str(node.get_id())
    did = hashlib.sha224(did).hexdigest()
    return did

def set_id_parameter_data(dataflow, vid):
    """Get an uid for the input data of the task (vid)
    Only input data of root nodes.

    Returns:
        (str) : the id of the data
    """
    node = dataflow.node(vid)
    did=""
    did = str(node.factory.name)
    did = did + str(node.inputs)
    return hashlib.sha224(did).hexdigest() 