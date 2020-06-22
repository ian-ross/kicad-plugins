from __future__ import print_function
import os.path
import re
import sys
import pcbnew

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

        print('New sheet from:', file)

        self.xrange = [None, None]
        self.yrange = [None, None]

        try:
            with open(file) as fp:
                state = None
                component_ref = None
                component_pos = None
                sheet_name = None
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
                        component_pos = None
                    if line == '$Sheet':
                        state = 'in-sheet'
                    if line == '$EndSheet':
                        state = None
                        sheet_name = None
                        sheet_file = None

                    # Handle component lines.
                    if state == 'in-component':
                        if line.startswith('L '):
                            component_ref = tokens(line)[2]
                        if line.startswith('P '):
                            component_pos = tuple(map(int, tokens(line)[1:]))
                        # If we have a component reference and a
                        # component position, record them and include
                        # the component position in the coordinate
                        # ranges.
                        if component_ref is not None and component_pos is not None:
                            self.components[component_ref] = component_pos
                            self.extend_range(component_pos[0], component_pos[1])
                            component_ref = None
                            component_pos = None

                    # Handle sub-sheet lines.
                    if state == 'in-sheet':
                        if line.startswith('S '):
                            sheet_bounds = tuple(map(int, tokens(line)[1:]))
                        if line.startswith('F0 '):
                            sheet_name = line.split('"')[1]
                        if line.startswith('F1 '):
                            sheet_file = line.split('"')[1]
                        # If we have a sheet name, sheet filename and
                        # sheet bounds, record them and include the
                        # bounds in the coordinate ranges.
                        if (sheet_name is not None and
                            sheet_file is not None and
                            sheet_bounds is not None):
                            self.sub_sheets[sheet_name] = sheet_file
                            self.extend_range(sheet_bounds[0], sheet_bounds[1])
                            self.extend_range(sheet_bounds[0] + sheet_bounds[2],
                                              sheet_bounds[1] + sheet_bounds[3])
                            sheet_name = None
                            sheet_file = None
                            sheet_bounds = None

        except Exception as err:
            print('Failed reading schematic file:', err)
            sys.exit(1)

POS_SCALE = 15000

def move_modules(components, board, xsize, ysize):
    for module in board.GetModules():
        old_pos = module.GetPosition()
        ref = module.GetReference()
        if ref in components:
            pos, sheet, idx = components[ref]
            new_pos = pcbnew.wxPoint(pos[0] * POS_SCALE, (pos[1] + idx * ysize) * POS_SCALE)
            module.SetPosition(new_pos)

class SchematicPositionsToLayoutPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Schematic positions -> PCB positions"
        self.category = "Modify PCB"
        self.description = "Layout components on PCB in same spatial relationships as components on schematic"

    def Run(self):
        board = pcbnew.GetBoard()
        work_dir, in_pcb_file = os.path.split(board.GetFileName())
        os.chdir(work_dir)
        root_schematic_file = os.path.splitext(in_pcb_file)[0] + '.sch'
        print('work_dir = {}'.format(work_dir), file=sys.stderr)
        print('in_pcb_file = {}'.format(in_pcb_file), file=sys.stderr)
        print('root_schematic_file = {}'.format(root_schematic_file), file=sys.stderr)

        # Read schematic sheets, starting at root sheet and following
        # links to sub-sheets.
        sheets = dict()
        sheet_queue = dict()
        sheet_queue['/'] = root_schematic_file
        while len(sheet_queue) > 0:
            sheet_name = list(sheet_queue)[0]
            if sheet_name in sheets:
                print('Oops. Sheet "{}" turned up twice!'.format(sheet_name))
                sys.exit(1)
            file_name = sheet_queue.pop(sheet_name)
            sheet = SchSheet(file_name)
            sheets[sheet_name] = sheet
            for sub_sheet_name in sheet.sub_sheets:
                sheet_queue[sub_sheet_name] = sheet.sub_sheets[sub_sheet_name]

        # Find maximum coordinate range across all sheets. We'll use this
        # for the size of each sub-sheet in the layout.
        xsize = sheets['/'].xrange[1] - sheets['/'].xrange[0]
        ysize = sheets['/'].yrange[1] - sheets['/'].yrange[0]
        for sname in sheets:
            s = sheets[sname]
            xsize = max(xsize, s.xrange[1] - s.xrange[0])
            ysize = max(ysize, s.yrange[1] - s.yrange[0])

        # Make a master component map, recording the component's position
        # in the sheet and the index of the sheet that it's on.
        components = dict()
        s = sheets['/']
        for cid in s.components:
            components[cid] = (s.components[cid], '/', 0)
        index = 1
        for sheet_name in sheets:
            if sheet_name == '/':
                continue
            s = sheets[sheet_name]
            for cid in s.components:
                components[cid] = (s.components[cid], sheet_name, index)
            index += 1

        # Move the components.
        move_modules(components, board, xsize, ysize)

SchematicPositionsToLayoutPlugin().register()
