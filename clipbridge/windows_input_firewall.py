"""The service changes only its own fixed, private-network input rule."""
RULE = "ClipBridge Input (UAC service)"


def update(program=None, port=None):
    import pythoncom
    from win32com.client.dynamic import Dispatch
    pythoncom.CoInitialize()
    try:
        policy = Dispatch("HNetCfg.FwPolicy2")
        try:
            policy.Rules.Remove(RULE)
        except pythoncom.com_error:
            pass
        if port is None:
            return
        if not 1024 <= port <= 65535:
            raise ValueError("Invalid input firewall port")
        rule = Dispatch("HNetCfg.FWRule")
        rule.Name, rule.Description = RULE, "ClipBridge paired input only; private LAN/Tailscale"
        rule.ApplicationName = str(program)
        rule.Protocol, rule.LocalPorts = 6, str(port)
        rule.RemoteAddresses = "LocalSubnet,100.64.0.0/10,fd7a:115c:a1e0::/48"
        rule.Direction, rule.Profiles, rule.Action = 1, 2, 1
        rule.Enabled, rule.EdgeTraversal = True, False
        policy.Rules.Add(rule)
    finally:
        pythoncom.CoUninitialize()
