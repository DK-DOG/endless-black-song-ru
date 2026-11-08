"""Parse and rebuild the Enigma Virtual Box filesystem inside EndlessBlackSong.exe."""
import struct

MAGIC_OFF = 0x187B42
ENIGMA1_RAW = 1604096
ENIGMA1_RSIZE = 858857472
ENIGMA2_RAW = 860461568
ENIGMA2_RSIZE = 315392
OPT_FILE_SIZE = 53
ORIG_OFF = 2
STORED_OFF = 49


def read_exact(f, n):
    b = f.read(n)
    if len(b) != n:
        raise EOFError("short read at %x" % f.tell())
    return b


def enigma1_raw_size(f):
    f.seek(0x3C)
    e_lfanew = struct.unpack("<I", f.read(4))[0]
    f.seek(e_lfanew + 6)
    nsec = struct.unpack("<H", f.read(2))[0]
    f.seek(e_lfanew + 20)
    optsize = struct.unpack("<H", f.read(2))[0]
    sec_off = e_lfanew + 24 + optsize
    for i in range(nsec):
        f.seek(sec_off + i * 40)
        name = f.read(8)
        rest = f.read(16)
        if name.startswith(b".enigma1"):
            vsize, _va, rsize = struct.unpack("<III", rest[:12])
            return rsize
    raise RuntimeError("no .enigma1 section")


def parse_vfs(f):
    f.seek(MAGIC_OFF)
    sig = read_exact(f, 4)
    if sig != b"EVB\x00":
        raise RuntimeError("bad EVB magic")
    pack_rest = read_exact(f, 60)
    main_pos = f.tell()
    main = bytearray(read_exact(f, 16))
    main_size = struct.unpack_from("<I", main, 0)[0]
    f.seek(-1, 1)
    table_start = f.tell()
    data_start = main_pos + 16 + main_size - 12

    nodes = []
    max_obj = 0
    cur = 0
    while f.tell() < data_start:
        node_pos = f.tell()
        hdr = bytearray(read_exact(f, 16))
        hcount = struct.unpack_from("<I", hdr, 12)[0]
        name = bytearray()
        while True:
            p = read_exact(f, 2)
            if p == b"\x00\x00":
                break
            name.extend(p)
        typ = read_exact(f, 1)[0]
        node = {
            "pos": node_pos,
            "hdr": hdr,
            "name": name.decode("utf-16-le"),
            "type": typ,
            "count": hcount,
        }
        if typ == 2:
            opt_pos = f.tell()
            opt = bytearray(read_exact(f, OPT_FILE_SIZE))
            node["opt_pos"] = opt_pos
            node["opt"] = opt
            node["original"] = struct.unpack_from("<I", opt, ORIG_OFF)[0]
            node["stored"] = struct.unpack_from("<I", opt, STORED_OFF)[0]
            cur += 1
        elif typ == 3:
            node["extra"] = read_exact(f, 25)
            max_obj += hcount
            cur += 1
        else:
            f.seek(node_pos)
            break
        nodes.append(node)
        if max_obj and cur > max_obj:
            break

    table_end = f.tell()
    if table_end > data_start:
        raise RuntimeError("table overran data start")
    trailing = read_exact(f, data_start - table_end)

    offset = data_start
    files = []
    for node in nodes:
        if node["type"] != 2:
            continue
        node["offset"] = offset
        offset += node["stored"]
        files.append(node)
    payload_end = offset
    section_end = ENIGMA1_RAW + enigma1_raw_size(f)
    if payload_end > section_end:
        raise RuntimeError("payload past section")
    return {
        "pack_rest": pack_rest,
        "main": main,
        "main_pos": main_pos,
        "main_size": main_size,
        "table_start": table_start,
        "table_end": table_end,
        "trailing": trailing,
        "data_start": data_start,
        "payload_end": payload_end,
        "section_pad": section_end - payload_end,
        "nodes": nodes,
        "files": files,
    }


def build_tree(nodes):
    """Attach children using folder counts. Returns root node."""
    idx = 0

    def take():
        nonlocal idx
        node = nodes[idx]
        idx += 1
        node["children"] = []
        if node["type"] == 3:
            for _ in range(node["count"]):
                node["children"].append(take())
        return node

    root = take()
    if idx != len(nodes):
        raise RuntimeError("tree walk left %d nodes" % (len(nodes) - idx))
    return root


def iter_files(root, prefix=""):
    name = root["name"]
    if name == "%DEFAULT FOLDER%":
        path = prefix
    else:
        path = prefix + name
    if root["type"] == 3:
        base = path + "\\" if path else ""
        for child in root["children"]:
            yield from iter_files(child, base)
    elif root["type"] == 2:
        yield path, root
