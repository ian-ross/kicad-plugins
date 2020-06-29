from __future__ import print_function
import os.path
import re
import sys
import pcbnew

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

POS_SCALE = 15000

def move_modules(components, board, offsets):
    for module in board.GetModules():
        old_pos = module.GetPosition()
        ref = module.GetReference()
        path = module.GetPath()
        if path in components:
            ref, pos, sheet = components[path]
            offset = offsets[sheet]
            new_pos = pcbnew.wxPoint(pos[0] * POS_SCALE, (pos[1] + offset) * POS_SCALE)
            print('path =', path, '  sheet =', sheet, '  ref =', ref,
                  '  pos =', pos, '  new_pos =', new_pos, file=DEBUG)
            module.SetPosition(new_pos)

class SchematicPositionsToLayoutPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Schematic positions -> PCB positions"
        self.category = "Modify PCB"
        self.description = "Layout components on PCB in same spatial relationships as components on schematic"

    def Run(self):
        global DEBUG
        DEBUG = open('schematic-positions-to-layout.debug', 'w')
        try:
            self.DoRun()
        finally:
            DEBUG.close()

    def DoRun(self):
        board = pcbnew.GetBoard()
        work_dir, in_pcb_file = os.path.split(board.GetFileName())
        os.chdir(work_dir)
        root_schematic_file = os.path.splitext(in_pcb_file)[0] + '.sch'
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
            sheet = SchSheet(file_name)
            sheets[sheet_path] = sheet
            for sub_sheet_name in sheet.sub_sheets:
                sheet_queue[sheet_path + '/' + sub_sheet_name] = sheet.sub_sheets[sub_sheet_name]

        # Find coordinate offsets for placement of each sub-sheet in
        # the layout.
        offsets = dict()
        offsets[''] = 0
        running_offset = sheets[''].yrange[1] - sheets[''].yrange[0]
        for sname in sheets:
            if sname == '':
                continue
            s = sheets[sname]
            offsets[sname] = running_offset
            running_offset += s.yrange[1] - s.yrange[0]

        # Make a master component map, recording the component's
        # position in the sheet.
        components = dict()
        s = sheets['']
        for cid in s.components:
            components[cid] = s.components[cid] + tuple([''])
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
        move_modules(components, board, offsets)

SchematicPositionsToLayoutPlugin().register()
