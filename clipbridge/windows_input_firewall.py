"""The service changes only its own fixed, private-network input rule."""
RULE = "ClipBridge Input (UAC service)"
SETUP_RULE = "ClipBridge Input setup (UAC service)"


def update(program=None, port=None):
    return _update(RULE, program, port)


def update_setup(program=None, port=None):
    return _update(SETUP_RULE, program, port)


def _update(name, program, port):
    import pythoncom
    from win32com.client.dynamic import Dispatch
    pythoncom.CoInitialize()
    try:
        policy = Dispatch("HNetCfg.FwPolicy2")
        try:
            policy.Rules.Remove(name)
        except pythoncom.com_error:
            pass
        if port is None:
            return
        ports = port if isinstance(port, tuple) else (port,)
        if not ports or any(type(item) is not int or not 1024 <= item <= 65535 for item in ports):
            raise ValueError("Invalid input firewall port")
        rule = Dispatch("HNetCfg.FWRule")
        rule.Name, rule.Description = name, "ClipBridge paired input only; private LAN/Tailscale"
        rule.ApplicationName = str(program)
        rule.Protocol, rule.LocalPorts = 6, ",".join(map(str, ports))
        rule.RemoteAddresses = "LocalSubnet,100.64.0.0/10,fd7a:115c:a1e0::/48"
        rule.Direction, rule.Profiles, rule.Action = 1, 2, 1
        rule.Enabled, rule.EdgeTraversal = True, False
        policy.Rules.Add(rule)
    finally:
        pythoncom.CoUninitialize()
