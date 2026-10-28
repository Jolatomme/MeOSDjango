from http.server import HTTPServer, BaseHTTPRequestHandler
import xml.etree.ElementTree as ET

HOST = "0.0.0.0"
PORT = 8080

class MIPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Read headers sent by MeOS MIP client
        competition_id = self.headers.get("competition", "100")
        last_id = int(self.headers.get("lastid", "0"))
        # 2. Check if MeOS has already received this runner entry
        entry_id = 101  # Unique integer ID for this entry
        if last_id < entry_id:
            # Generate XML payload adding a runner with Disqualified (DQ / 5) status
            xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<MIPData xmlns="http://www.melin.nu/mip" lastid="{entry_id}">
  <entry id="{entry_id}" classname="H21" fee="0.0" paid="true">
    <name birthyear="1995">Dupont, Jean</name>
    <club>Club Orientation</club>
    <card hired="false">8123456</card>
    <bib>42</bib>
    <status>DQ</status>
  </entry>
</MIPData>"""
            new_lastid = entry_id
        else:
            # Nothing new to send to MeOS
            xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<MIPData xmlns="http://www.melin.nu/mip" lastid="{last_id}">
</MIPData>"""

        # 3. Return response to MeOS
        response_bytes = xml_response.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)


def run_server():
    server = HTTPServer((HOST, PORT), MIPRequestHandler)
    print(f"MIP Server running on http://{HOST}:{PORT}")
    print("In MeOS: Configure 'Online Input' with this URL.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
        server.server_close()


if __name__ == "__main__":
    run_server()
