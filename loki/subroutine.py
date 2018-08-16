from collections import OrderedDict

from loki.frontend.parse import parse, OFP, OMNI
from loki.frontend.preprocessing import blacklist
from loki.ir import (Declaration, Allocation, Import, Section, Call,
                     CallContext, CommentBlock, Intrinsic)
from loki.expression import Variable, ExpressionVisitor
from loki.types import BaseType, DerivedType
from loki.visitors import FindNodes, Visitor, Transformer
from loki.tools import flatten, as_tuple


__all__ = ['Subroutine']


class InterfaceBlock(object):

    def __init__(self, name, arguments, imports, declarations):
        self.name = name
        self.arguments = arguments
        self.imports = imports
        self.declarations = declarations


class Subroutine(object):
    """
    Class to handle and manipulate a single subroutine.

    :param name: Name of the subroutine
    :param ast: OFP parser node for this subroutine
    :param raw_source: Raw source string, broken into lines(!), as it
                       appeared in the parsed source file.
    :param typedefs: Optional list of external definitions for derived
                     types that allows more detaild type information.
    """

    def __init__(self, name, args=None, docstring=None, spec=None,
                 body=None, members=None, ast=None):
        self.name = name
        self._ast = ast

        self.arguments = None
        self.variables = None

        self.docstring = docstring
        self.spec = spec
        self.body = body
        self.members = members

    @classmethod
    def from_ofp(cls, ast, raw_source, name=None, typedefs=None, pp_info=None):
        name = name or ast.attrib['name']

        # Store the names of variables in the subroutine signature
        arg_ast = ast.findall('header/arguments/argument')
        args = [arg.attrib['name'].upper() for arg in arg_ast]

        # Create a IRs for declarations section and the loop body
        body = parse(ast.find('body'), raw_source=raw_source, frontend=OFP)

        # Apply postprocessing rules to re-insert information lost during preprocessing
        for r_name, rule in blacklist.items():
            info = pp_info[r_name] if pp_info is not None and r_name in pp_info else None
            body = rule.postprocess(body, info)

        # Parse "member" subroutines recursively
        members = None
        if ast.find('members'):
            members = [Subroutine.from_ofp(ast=s, raw_source=raw_source,
                                           typedefs=typedefs, pp_info=pp_info)
                       for s in ast.findall('members/subroutine')]

        # Separate docstring and declarations
        docstring = body[0] if isinstance(body[0], CommentBlock) else None
        spec = FindNodes(Section).visit(body)[0]
        body = Transformer({docstring: None, spec: None}).visit(body)

        obj = cls(name=name, args=args, docstring=docstring,
                  spec=spec, body=body, members=members, ast=ast)

        # Internalize argument declarations
        obj._internalize()

        # Enrich internal representation with meta-data
        obj._attach_derived_types(typedefs=typedefs)
        obj._derive_variable_shape(typedefs=typedefs)

        return obj

    @classmethod
    def from_omni(cls, ast, raw_source, typetable, name=None, symbol_map=None, typedefs=None):
        name = name or ast.find('name').text
        file = ast.attrib['file']
        type_map = {t.attrib['type']: t for t in typetable}
        symbol_map = symbol_map or {s.attrib['type']: s for s in ast.find('symbols')}

        # Get the names of dummy variables from the type_map
        fhash = ast.find('name').attrib['type']
        ftype = [t for t in typetable.findall('FfunctionType')
                 if t.attrib['type'] == fhash][0]
        args = as_tuple(name.text for name in ftype.findall('params/name'))

        # Generate spec, filter out external declarations and docstring
        spec = parse(ast.find('declarations'), type_map=type_map,
                     symbol_map=symbol_map, raw_source=raw_source, frontend=OMNI)
        mapper = {d: None for d in FindNodes(Declaration).visit(spec)
                  if d._source.file != file or d.variables[0] == name}
        spec = Section(body=Transformer(mapper).visit(spec))

        # Insert the `implicit none` statement OMNI omits (slightly hacky!)
        implicit_none = Intrinsic(text='IMPLICIT NONE')
        first_decl = FindNodes(Declaration).visit(spec)[0]
        spec_body = list(spec.body)
        i = spec_body.index(first_decl)
        spec_body.insert(i, implicit_none)
        spec._update(body=as_tuple(spec_body))

        # TODO: Parse member functions properly
        contains = ast.find('body/FcontainsStatement')
        members = None
        if contains is not None:
            members = [Subroutine.from_omni(ast=s, typetable=typetable, symbol_map=symbol_map,
                                            typedefs=typedefs, raw_source=raw_source)
                       for s in contains]
            # Strip members from the XML before we proceed
            ast.find('body').remove(contains)

        # Convert the core kernel to IR
        body = parse(ast.find('body'), type_map=type_map, symbol_map=symbol_map,
                     raw_source=raw_source, frontend=OMNI)

        obj = cls(name=name, args=args, docstring=None, spec=spec, body=body,
                  members=members, ast=ast)

        # Internalize argument declarations
        obj._internalize()

        # Enrich internal representation with meta-data
        obj._attach_derived_types(typedefs=typedefs)
        obj._derive_variable_shape(typedefs=typedefs)

        return obj

    def _internalize(self):
        """
        Internalize argument and variable declarations.
        """
        self.arguments = []
        self.variables = []
        self._decl_map = OrderedDict()
        dmap = {}

        for decl in FindNodes(Declaration).visit(self.ir):
            # Propagate dimensions to variables
            dvars = as_tuple(decl.variables)
            if decl.dimensions is not None:
                for v in dvars:
                    v.dimensions = decl.dimensions

            # Record arguments and variables independently
            self.variables += list(dvars)
            if decl.type.intent is not None:
                self.arguments += list(dvars)

            # Stash declaration and mark for removal
            for v in dvars:
                self._decl_map[v] = decl
            dmap[decl] = None

        # Remove declarations from the IR
        self.spec = Transformer(dmap).visit(self.spec)

    def _externalize(self):
        """
        Re-insert argument declarations...
        """
        # A hacky way to ensure we don;t do this twice
        if self._decl_map is None:
            return

        decls = []
        for v in self.variables:
            d = self._decl_map[v].clone()
            d.variables = as_tuple(v)
            # Dimension declarations are done on variables
            d.dimensions = None

            decls += [d]
        self.spec.append(decls)

        self._decl_map = None

    def enrich_calls(self, routines):
        """
        Attach target :class:`Subroutine` object to :class:`Call`
        objects in the IR tree.

        :param call_targets: :class:`Subroutine` objects for corresponding
                             :class:`Call` nodes in the IR tree.
        :param active: Additional flag indicating whether this :call:`Call`
                       represents an active/inactive edge in the
                       interprocedural callgraph.
        """
        routine_map = {r.name.upper(): r for r in as_tuple(routines)}

        for call in FindNodes(Call).visit(self.body):
            if call.name.upper() in routine_map:
                # Calls marked as 'reference' are inactive and thus skipped
                active = True
                if call.pragma is not None and call.pragma.keyword == 'loki':
                    active = not call.pragma.content.startswith('reference')

                context = CallContext(routine=routine_map[call.name.upper()],
                                      active=active)
                call._update(context=context)

        # TODO: Could extend this to module and header imports to
        # facilitate user-directed inlining.

    def _attach_derived_types(self, typedefs=None):
        """
        Attaches the derived type definition from external header
        files to all :class:`Variable` instances (in-place).
        """
        for v in self.variables:
            if typedefs is not None and v.type is not None and v.type.name.upper() in typedefs:
                typedef = typedefs[v.type.name.upper()]
                derived_type = DerivedType(name=typedef.name, variables=typedef.variables,
                                           intent=v.type.intent, allocatable=v.type.allocatable,
                                           pointer=v.type.pointer, optional=v.type.optional)
                v._type = derived_type

    def _derive_variable_shape(self, declarations=None, typedefs=None):
        """
        Propgates the allocated dimensions (shape) from variable
        declarations to :class:`Variables` instances in the code body.

        :param ir: The control-flow IR into which to inject shape info
        :param declarations: Optional list of :class:`Declaration`s from
                             which to get shape dimensions.
        :param typdefs: Optional, additional derived-type definitions
                        from which to infer sub-variable shapes.

        Note, the shape derivation from derived types is currently
        limited to first-level nesting only.
        """
        declarations = declarations or FindNodes(Declaration).visit(self.spec)
        typedefs = typedefs or {}

        # Create map of variable names to allocated shape (dimensions)
        # Make sure you capture sub-variables.
        shapes = {}
        derived = {}
        for decl in declarations:
            if decl.type.name.upper() in typedefs:
                derived.update({v.name: typedefs[decl.type.name.upper()]
                                for v in decl.variables})

            if decl.dimensions is not None:
                shapes.update({v.name: decl.dimensions for v in decl.variables})
            else:
                shapes.update({v.name: v.dimensions for v in decl.variables
                               if v.dimensions is not None and len(v.dimensions) > 0})

        # Override shapes for deferred-shape allocations
        for alloc in FindNodes(Allocation).visit(self.body):
            shapes[alloc.variable.name] = alloc.variable.dimensions

        class VariableShapeInjector(ExpressionVisitor, Visitor):
            """
            Attach shape information to :class:`Variable` via the
            ``.shape`` attribute.
            """
            def __init__(self, shapes, derived):
                super(VariableShapeInjector, self).__init__()
                self.shapes = shapes
                self.derived = derived

            def visit_Variable(self, o):
                if o.name in self.shapes:
                    o._shape = self.shapes[o.name]

                if o.ref is not None and o.ref.name in self.derived:
                    # We currently only follow a single level of nesting
                    typevars = {v.name.upper(): v for v in self.derived[o.ref.name].variables}
                    o._shape = typevars[o.name.upper()].dimensions

                # Recurse over children
                for c in o.children:
                    self.visit(c)

            def visit_Declaration(self, o):
                # Attach shape info to declaration dummy variables
                if o.type.allocatable:
                    for v in o.variables:
                        v._shape = self.shapes[v.name]

                # Recurse over children
                for c in o.children:
                    self.visit(c)

        # Apply dimensions via expression visitor (in-place)
        VariableShapeInjector(shapes=shapes, derived=derived).visit(self.ir)

    @property
    def ir(self):
        """
        Intermediate representation (AST) of the body in this subroutine
        """
        return (self.docstring, self.spec, self.body)

    @property
    def argnames(self):
        return [a.name for a in self.arguments]

    @property
    def variable_map(self):
        """
        Map of variable names to `Variable` objects
        """
        return {v.name.lower(): v for v in self.variables}

    @property
    def interface(self):
        arguments = self.arguments
        declarations = tuple(d for d in FindNodes(Declaration).visit(self.spec)
                             if any(v in arguments for v in d.variables))

        # Collect unknown symbols that we might need to import
        undefined = set()
        anames = [a.name for a in arguments]
        for decl in declarations:
            # Add potentially unkown TYPE and KIND symbols to 'undefined'
            if decl.type.name.upper() not in BaseType._base_types:
                undefined.add(decl.type.name)
            if decl.type.kind and not decl.type.kind.isdigit():
                undefined.add(decl.type.kind)
            # Add (pure) variable dimensions that might be defined elsewhere
            for v in decl.variables:
                undefined.update([str(d) for d in v.dimensions
                                  if isinstance(d, Variable) and d not in anames])

        # Create a sub-list of imports based on undefined symbols
        imports = []
        for use in self.imports:
            symbols = tuple(s for s in use.symbols if s in undefined)
            if len(symbols) > 0:
                imports += [Import(module=use.module, symbols=symbols)]

        return InterfaceBlock(name=self.name, imports=imports,
                              arguments=arguments, declarations=declarations)
