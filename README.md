# Miscellaneous plugins for KiCad

## Reproduce schematic layout in PCB layout

Based on an original idea by @jenschr

The `SchematicPositionsToLayout.py` plugin helps with the initial
organisation of parts when first creating a PCB layout from a
schematic. Install the `SchematicPositionsToLayout.py` in your KiCad
plugins folder and refresh your plugin list in Pcbnew. Then to use
the plugin:

1. Create a netlist from your schematic.

2. Create a new PCB layout and import the netlist you created.

3. Select "Schematic positions -> PCB positions" from the "Tools" ->
   "External plugins..." menu in Pcbnew.

The result of this action will be that the component footprints in
Pcbnew will be laid out in the same pattern as their corresponding
components in the schematic. Hierarchical sheets are laid out one
after another down the page in non-overlapping areas.

The movement of the component footprints by the plugin is a normal
editing action, so can be undone if you don't like what you see.

Note that the footprint organisation produced by this script is
intended only to aid with keeping track of where everything is at the
very start of component placement. For example, if you have a large
number of decoupling capacitors for a component, you can place them
near to the component in the schematic and the plugin will move them
to be near to the component in the layout too. Another example where
this might be useful is for analog sections where it might be useful
to mirror signal flow and component placement on the schematic in an
initial view of the PCB layout.
