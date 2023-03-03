from __future__ import print_function
import os
import re
import sys
import pcbnew
from collections import defaultdict
import shlex


if hasattr(pcbnew, 'GetBuildVersion'):
    BUILD_VERSION = pcbnew.GetBuildVersion()
    MAJOR, MINOR = tuple(map(int, BUILD_VERSION.strip('()').split('~')[0].split('.')[:2]))
    if MAJOR >= 6 or MAJOR == 5 and MINOR == 99:
        ENABLE_KICAD_V6_API=True
    else:
        ENABLE_KICAD_V6_API=False
else:
    BUILD_VERSION = "Unknown"
    ENABLE_KICAD_V6_API = False


DEBUG = None

# Tokenizer for schematic file input lines.
def tokens(s):
    return re.split(r' +', s)

# Class to represent a single sheet of a schematic. Has a map from
# component IDs to positions, a map from sub-sheet names to sub-sheet
# schematic file names, plus coordinate ranges for the component
# positions.
class SchSheet:
    # Extend x- and y-coordinate ranges based on new component or
    # sub-sheet values.
    def extend_range(self, x, y):
        if self.xrange[0] is None or x < self.xrange[0]:
            self.xrange[0] = x
        if self.xrange[1] is None or x > self.xrange[1]:
            self.xrange[1] = x
        if self.yrange[0] is None or y < self.yrange[0]:
            self.yrange[0] = y
        if self.yrange[1] is None or y > self.yrange[1]:
            self.yrange[1] = y

    # Initialise from schematic file.
    def __init__(self, file):
        self.components = dict()
        self.sub_sheets = dict()

        print('New sheet from:', file, file=DEBUG)

        self.xrange = [None, None]
        self.yrange = [None, None]

        try:
            with open(file) as fp:
                state = None
                component_ref = None
                component_id = None
                component_pos = None
                sheet_name = None
                sheet_id = None
                sheet_file = None
                sheet_bounds = None
                for line in fp:
                    line = line.strip()

                    # Process start and end of component and start and
                    # end of sheet lines.
                    if line == '$Comp':
                        state = 'in-component'
                    if line == '$EndComp':
                        state = None
                        component_ref = None
                        component_id = None
                        component_pos = None
                    if line == '$Sheet':
                        state = 'in-sheet'
                    if line == '$EndSheet':
                        state = None
                        sheet_name = None
                        sheet_id = None
                        sheet_file = None
                        sheet_bounds = None

                    # Handle component lines.
                    if state == 'in-component':
                        if line.startswith('L '):
                            component_ref = tokens(line)[2]
                        if line.startswith('U '):
                            component_id = tokens(line)[3]
                        if line.startswith('P '):
                            component_pos = tuple(map(int, tokens(line)[1:]))
                        # If we have a component reference and a
                        # component position, record them and include
                        # the component position in the coordinate
                        # ranges.
                        if (component_ref is not None and
                            component_id is not None and
                            component_pos is not None):
                            self.components[component_id] = (component_ref, component_pos)
                            self.extend_range(component_pos[0], component_pos[1])
                            component_ref = None
                            component_id = None
                            component_pos = None

                    # Handle sub-sheet lines.
                    if state == 'in-sheet':
                        if line.startswith('S '):
                            sheet_bounds = tuple(map(int, tokens(line)[1:]))
                        if line.startswith('U '):
                            sheet_id = tokens(line)[1]
                        if line.startswith('F0 '):
                            sheet_name = line.split('"')[1]
                        if line.startswith('F1 '):
                            sheet_file = line.split('"')[1]
                        # If we have a sheet name, sheet filename and
                        # sheet bounds, record them and include the
                        # bounds in the coordinate ranges.
                        if (sheet_name is not None and
                            sheet_id is not None and
                            sheet_file is not None and
                            sheet_bounds is not None):
                            self.sub_sheets[sheet_id] = (sheet_name, sheet_file)
                            self.extend_range(sheet_bounds[0], sheet_bounds[1])
                            self.extend_range(sheet_bounds[0] + sheet_bounds[2],
                                              sheet_bounds[1] + sheet_bounds[3])
                            sheet_name = None
                            sheet_id = None
                            sheet_file = None
                            sheet_bounds = None

        except Exception as err:
            print('Failed reading schematic file:', err, file=DEBUG)
            sys.exit(1)

class SchSheetV6(SchSheet):
    def __init__(self, file):
        self.components = dict()
        self.sub_sheets = dict()

        print('New sheet from:', file)

        self.xrange = [None, None]
        self.yrange = [None, None]

        ast = self.parse_ast(file)
        self.walk(ast)

    def parse_ast(self, filename):
        Symbol = str              # A Scheme Symbol is implemented as a Python str
        Number = (int, float)     # A Scheme Number is implemented as a Python int or float
        Atom   = (Symbol, Number) # A Scheme Atom is a Symbol or Number
        List   = list             # A Scheme List is implemented as a Python list
        Exp    = (Atom, List)     # A Scheme expression is an Atom or List
        Env    = dict             # A Scheme environment (defined below) 
                                  # is a mapping of {variable: value}

        def tokenize(chars: str) -> list:
            "Convert a string of characters into a list of tokens."
            return shlex.split(chars.replace('(', ' ( ').replace(')', ' ) '))

        def parse(program: str) -> Exp:
            "Read a Scheme expression from a string."
            return read_from_tokens(tokenize(program))

        def read_from_tokens(tokens: list) -> Exp:
            "Read an expression from a sequence of tokens."
            if len(tokens) == 0:
                raise SyntaxError('unexpected EOF')
            token = tokens.pop(0)
            if token == '(':
                L = []
                while tokens[0] != ')':
                    L.append(read_from_tokens(tokens))
                tokens.pop(0) # pop off ')'
                return L
            elif token == ')':
                raise SyntaxError('unexpected )')
            else:
                return atom(token)

        def atom(token: str) -> Atom:
            "Numbers become numbers; every other token is a symbol."
            try: return int(token)
            except ValueError:
                try: return float(token)
                except ValueError:
                    return Symbol(token)
        
        with open(filename,encoding='utf-8') as f:
            data = f.read()

        #ast = OneOrMore(nestedExpr()).parseString(data, parseAll=True)
        ast = parse(data)
        return ast
    
    def pick(self, lst, *attribute_names):
        attr_pool = defaultdict(list)
        for i in attribute_names:
            values = i.split()
            attr_pool[values[0]].append(values)
        obj = {}
        for item in lst:
            if item[0] in attr_pool:
                token_len = len(attr_pool[item[0]][0])
                if token_len == 1:  # simple case, direct match
                    obj[item[0]] = item[1:]
                else:  # complex, try matching tail tokens
                    for tokens in attr_pool[item[0]]:
                        if item[:len(tokens)] == tokens:  # match
                            obj[' '.join(tokens)] = item[len(tokens):]
                            break
        #print("pick:", attribute_names, "got:", obj)
        return obj

    def pick_property(self, lst, prop_name=None, prop_id=None):
        for item in lst:
            if item[0] == 'property' and ( \
                                           (prop_name is not None and item[1] == prop_name) or \
                                           (prop_id is not None and int(self.pick(item[1:], 'id')['id'][0]) == prop_id)):
                #print("prop get:", item[2])
                return item[2]

    def walk(self, ast):
        def position_convert(x: str):
            return int(float(x)*100)
        
        for i in ast:
            token = i[0]
            if token == 'symbol':  #  Process start and end of component
                component_ref = self.pick_property(i[1:], prop_id=0)
                component_id = self.pick(i[1:], "uuid")['uuid'][0]
                component_pos = tuple(map(position_convert, self.pick(i[1:], "at")['at']))[:2]
                self.components[component_id] = (component_ref, component_pos)
                self.extend_range(component_pos[0], component_pos[1])
            elif token == 'sheet': # Handle sub-sheet
                sheet_bounds_ast = self.pick(i[1:], 'at', 'size')
                sheet_bounds = tuple(map(position_convert, sheet_bounds_ast['at'] + sheet_bounds_ast['size']))
                sheet_id = self.pick(i[1:], "uuid")['uuid'][0]
                sheet_name = self.pick_property(i[1:], prop_id=0)
                sheet_file = self.pick_property(i[1:], prop_id=1)
                self.sub_sheets[sheet_id] = (sheet_name, sheet_file)
                self.extend_range(sheet_bounds[0], sheet_bounds[1])
                self.extend_range(sheet_bounds[0] + sheet_bounds[2],
                                  sheet_bounds[1] + sheet_bounds[3])

POS_SCALE = 15000

def move_modules(components, board, offsets, kicad_v6=False):
    for module in board.GetModules() if kicad_v6 is False else board.GetFootprints():
        old_pos = module.GetPosition()
        ref = module.GetReference()
        path = module.GetPath() if kicad_v6 is False else '/' + '/'.join([x.AsString() for x in module.GetPath()])
        print(ref, path, file=DEBUG)

        if path in components:
            ref, pos, sheet = components[path]
            if module.IsLocked():
                print('  path =', path, '  sheet =', sheet, '  ref =', ref, ' is locked, skip', file=DEBUG)
                continue

            offset = offsets[sheet]
            new_pos = pcbnew.wxPoint(pos[0] * POS_SCALE, (pos[1] + offset) * POS_SCALE)
            print('  path =', path, '  sheet =', sheet, '  ref =', ref,
                  '  pos =', pos, '  new_pos =', new_pos, file=DEBUG)
            module.SetPosition(new_pos)
        else:
            print('  NOT FOUND', file=DEBUG)


class SchematicPositionsToLayoutPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Schematic positions -> PCB positions"
        self.category = "Modify PCB"
        self.description = "Layout components on PCB in same spatial relationships as components on schematic"
        self.show_toolbar_button = True # Optional, defaults to False
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'sch2layout.png') # Optional, defaults to ""
    def Run(self):
        global DEBUG
        work_dir = os.path.dirname(pcbnew.GetBoard().GetFileName())
        DEBUG = open(os.path.join(work_dir, 'schematic-positions-to-layout.debug'), 'w')
        try:
            self.DoRun()
        finally:
            DEBUG.close()

    def DoRun(self):
        board = pcbnew.GetBoard()
        work_dir, in_pcb_file = os.path.split(board.GetFileName())
        os.chdir(work_dir)
        root_schematic_file = os.path.splitext(in_pcb_file)[0] + ('.kicad_sch' if ENABLE_KICAD_V6_API else '.sch')
        root_schematic_file = str(root_schematic_file) # 对Unicode中文的支持 (support for Chinese Unicode)
        print('work_dir = {}'.format(work_dir), file=DEBUG)
        print('in_pcb_file = {}'.format(in_pcb_file), file=DEBUG)
        print('root_schematic_file = {}'.format(root_schematic_file), file=DEBUG)

        # Read schematic sheets, starting at root sheet and following
        # links to sub-sheets.
        sheets = dict()
        sheet_queue = dict()
        sheet_queue[''] = ('', root_schematic_file)
        while len(sheet_queue) > 0:
            sheet_path = list(sheet_queue)[0]
            if sheet_path in sheets:
                print('Oops. Sheet "{}" turned up twice!'.format(sheet_path), file=DEBUG)
                sys.exit(1)
            sheet_name, file_name = sheet_queue.pop(sheet_path)
            sheet = SchSheetV6(file_name) if ENABLE_KICAD_V6_API else SchSheet(file_name)
            print('store to sheet[{}] = {}'.format(sheet_path, file_name), file=DEBUG)
            sheets[sheet_path] = sheet
            for sub_sheet_name in sheet.sub_sheets:
                sheet_queue[sheet_path + '/' + sub_sheet_name] = sheet.sub_sheets[sub_sheet_name]

        # Find coordinate offsets for placement of each sub-sheet in
        # the layout.
        offsets = dict()
        offsets[''] = 0
        OFFSET_FACTOR = 1.25
        running_offset = OFFSET_FACTOR * (sheets[''].yrange[1] - sheets[''].yrange[0])
        for sname in sheets:
            if sname == '':
                continue
            s = sheets[sname]
            offsets[sname] = running_offset
            running_offset += OFFSET_FACTOR * (s.yrange[1] - s.yrange[0])

        # Make a master component map, recording the component's
        # position in the sheet.
        components = dict()
        s = sheets['']
        for cid in s.components:
            components['/' + cid] = s.components[cid] + tuple([''])
        for sheet_name in sheets:
            if sheet_name == '':
                continue
            print('Processing', sheet_name, file=DEBUG)
            s = sheets[sheet_name]
            for cid in s.components:
                components[sheet_name + '/' + cid] = s.components[cid] + tuple([sheet_name])

        for cid in components:
            print(cid, components[cid], file=DEBUG)

        # Move the components.
        move_modules(components, board, offsets, kicad_v6=ENABLE_KICAD_V6_API)
        pcbnew.Refresh()

SchematicPositionsToLayoutPlugin().register()
