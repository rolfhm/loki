"""
Collection of utility routines to deal with general language conversion.


"""
import platform

from loki import Subroutine, Module
from loki.expression import (
    symbols as sym, FindVariables, FindInlineCalls, FindLiterals,
    SubstituteExpressions, SubstituteExpressionsMapper, FindTypedSymbols
)
from loki.ir import Associate, Import, TypeDef
from loki.visitors import Transformer, FindNodes
from loki.tools import CaseInsensitiveDict, as_tuple
from loki.types import SymbolType, BasicType, DerivedType, ProcedureType


__all__ = [
    'convert_to_lower_case', 'replace_intrinsics', 'resolve_associates',
    'sanitise_imports', 'replace_selected_kind'
]


def convert_to_lower_case(routine):
    """
    Converts all variables and symbols in a subroutine to lower-case.

    Note, this is intended for conversion to case-sensitive languages.

    TODO: Should be extended to `Module` objects.
    """

    # Force all variables in a subroutine body to lower-caps
    variables = FindVariables().visit(routine.ir)
    vmap = {v: v.clone(name=v.name.lower()) for v in variables
            if isinstance(v, (sym.Scalar, sym.Array)) and not v.name.islower()}

    # Capture nesting by applying map to itself before applying to the routine
    for _ in range(2):
        mapper = SubstituteExpressionsMapper(vmap)
        vmap = {k: mapper(v) for k, v in vmap.items()}

    routine.body = SubstituteExpressions(vmap).visit(routine.body)
    routine.spec = SubstituteExpressions(vmap).visit(routine.spec)

    # Down-case all subroutine arguments and variables
    mapper = SubstituteExpressionsMapper(vmap)

    routine.arguments = [mapper(arg) for arg in routine.arguments]
    routine.variables = [mapper(var) for var in routine.variables]


def replace_intrinsics(routine, function_map=None, symbol_map=None):
    """
    Replace known intrinsic functions and symbols.

    :param function_map: Map (string: string) for replacing intrinsic
                         functions (`InlineCall` objects).
    :param symbol_map: Map (string: string) for replacing intrinsic
                       symbols (`Variable` objects).
    """
    symbol_map = symbol_map or {}
    function_map = function_map or {}

    callmap = {}
    for c in FindInlineCalls(unique=False).visit(routine.body):
        cname = c.name.lower()

        if cname in symbol_map:
            callmap[c] = sym.Variable(name=symbol_map[cname], scope=routine.scope)

        if cname in function_map:
            fct_symbol = sym.ProcedureSymbol(function_map[cname], scope=routine.scope)
            callmap[c] = sym.InlineCall(fct_symbol, parameters=c.parameters,
                                        kw_parameters=c.kw_parameters)

    # Capture nesting by applying map to itself before applying to the routine
    for _ in range(2):
        mapper = SubstituteExpressionsMapper(callmap)
        callmap = {k: mapper(v) for k, v in callmap.items()}

    routine.body = SubstituteExpressions(callmap).visit(routine.body)


def resolve_associates(routine):
    """
    Resolve implicit struct mappings through "associates"
    """
    assoc_map = {}
    vmap = {}
    for assoc in FindNodes(Associate).visit(routine.body):
        invert_assoc = CaseInsensitiveDict({v.name: k for k, v in assoc.associations})
        for v in FindVariables(unique=False).visit(routine.body):
            if v.name in invert_assoc:
                vmap[v] = invert_assoc[v.name]
        assoc_map[assoc] = assoc.body
    routine.body = Transformer(assoc_map).visit(routine.body)
    routine.body = SubstituteExpressions(vmap).visit(routine.body)


def used_names_from_symbol(symbol, modifier=str.lower):
    """
    Helper routine that yields the symbol names for the different types of symbols
    we may encounter.
    """
    if isinstance(symbol, str):
        return {modifier(symbol)}

    if isinstance(symbol, sym.TypedSymbol):
        return {modifier(symbol.name)} | used_names_from_symbol(symbol.type, modifier=modifier)

    if isinstance(symbol, SymbolType):
        if isinstance(symbol.dtype, DerivedType):
            return {modifier(symbol.dtype.name)}
        if isinstance(symbol.dtype, BasicType) and symbol.kind is not None:
            return {modifier(str(symbol.kind))}

    if isinstance(symbol, (DerivedType, ProcedureType)):
        return {modifier(symbol.name)}

    return set()


def eliminate_unused_imports(module_or_routine, used_symbols):
    """
    Eliminate any imported symbols (or imports alltogether) that are not
    in the set of used symbols.
    """
    imports = FindNodes(Import).visit(module_or_routine.spec)
    imported_symbols = [s for im in imports for s in im.symbols or []]

    redundant_symbols = {s for s in imported_symbols if str(s).lower() not in used_symbols}

    if redundant_symbols:
        imprt_map = {}
        for im in imports:
            if im.symbols is not None:
                symbols = [s for s in im.symbols if s not in redundant_symbols]
                if not symbols:
                    # Symbol list is empty: Remove the import
                    imprt_map[im] = None
                elif len(symbols) < len(im.symbols):
                    # Symbol list is shorter than before: We need to replace that import
                    imprt_map[im] = im.clone(symbols=symbols)
        module_or_routine.spec = Transformer(imprt_map).visit(module_or_routine.spec)


def find_and_eliminate_unused_imports(routine):
    """
    Find all unused imported symbols and eliminate them from their import statements
    in the given routine and all contained members.
    Empty import statements are removed.

    The accumulated set of used symbols is returned.
    """
    # We need a custom expression retriever that does not return symbols used in Imports
    class SymbolRetriever(FindTypedSymbols):
        def visit_Import(self, o, **kwargs):  # pylint: disable=unused-argument,no-self-use
            return ()

    # Find all used symbols
    used_symbols = set.union(*[used_names_from_symbol(s)
                               for s in SymbolRetriever().visit([routine.spec, routine.body])])
    used_symbols |= set.union(*[used_names_from_symbol(s) for s in routine.variables])
    for typedef in FindNodes(TypeDef).visit(routine.spec):
        used_symbols |= set.union(*[used_names_from_symbol(s) for s in typedef.variables])

    # Recurse for contained subroutines/functions
    for member in routine.members:
        used_symbols |= find_and_eliminate_unused_imports(member)

    eliminate_unused_imports(routine, used_symbols)
    return used_symbols


def sanitise_imports(module_or_routine):
    """
    Sanitise imports by removing unused symbols and eliminating imports
    with empty symbol lists.

    Note that this is currently limited to imports that are identified to be :class:`Scalar`,
    :class:`Array`, or :class:`ProcedureSymbol`.
    """
    if isinstance(module_or_routine, Subroutine):
        find_and_eliminate_unused_imports(module_or_routine)
    elif isinstance(module_or_routine, Module):
        used_symbols = set()
        for routine in module_or_routine.subroutines:
            used_symbols |= find_and_eliminate_unused_imports(routine)
        eliminate_unused_imports(module_or_routine, used_symbols)


class IsoFortranEnvMapper:
    """
    Mapper to convert other Fortran kind specifications to their definitions
    from ``iso_fortran_env``.
    """

    selected_kind_calls = ('selected_int_kind', 'selected_real_kind')

    def __init__(self, arch=None):
        if arch is None:
            arch = platform.machine()
        self.arch = arch.lower()
        self.used_names = CaseInsensitiveDict()

    @classmethod
    def is_selected_kind_call(cls, call):
        """
        Return ``True`` if the given call is a transformational function to
        select the kind of an integer or real type.
        """
        return isinstance(call, sym.InlineCall) and call.name.lower() in cls.selected_kind_calls

    @staticmethod
    def _selected_int_kind(r):
        """
        Return number of bytes required by the smallest signed integer type that
        is able to represent all integers n in the range -10**r < n < 10**r.

        This emulates the behaviour of Fortran's ``SELECTED_INT_KIND(R)``.

        Source: numpy.f2py.crackfortran
        https://github.com/numpy/numpy/blob/9e26d1d2be7a961a16f8fa9ff7820c33b25415e2/numpy/f2py/crackfortran.py#L2431-L2444

        :returns int: the number of bytes or -1 if no such type exists.
        """
        m = 10 ** r
        if m <= 2 ** 8:
            return 1
        if m <= 2 ** 16:
            return 2
        if m <= 2 ** 32:
            return 4
        if m <= 2 ** 63:
            return 8
        if m <= 2 ** 128:
            return 16
        return -1

    def map_selected_int_kind(self, scope, r):
        """
        Return the kind of the smallest signed integer type defined in
        ``iso_fortran_env`` that is able to represent all integers n
        in the range -10**r < n < 10**r.
        """
        byte_kind_map = {b: 'INT{}'.format(8 * b) for b in [1, 2, 4, 8]}
        kind = self._selected_int_kind(r)
        if kind in byte_kind_map:
            kind_name = byte_kind_map[kind]
            self.used_names[kind_name] = sym.Variable(name=kind_name, scope=scope)
            return self.used_names[kind_name]
        return sym.IntLiteral(-1)

    def _selected_real_kind(self, p, r=0, radix=0):  # pylint: disable=unused-argument
        """
        Return number of bytes required by the smallest real type that fulfils
        the given requirements:

        - decimal precision at least ``p``;
        - decimal exponent range at least ``r``;
        - radix ``r``.

        This resembles the behaviour of Fortran's ``SELECTED_REAL_KIND([P, R, RADIX])``.
        NB: This honors only ``p`` at the moment!

        Source: numpy.f2py.crackfortran
        https://github.com/numpy/numpy/blob/9e26d1d2be7a961a16f8fa9ff7820c33b25415e2/numpy/f2py/crackfortran.py#L2447-L2463

        :returns int: the number of bytes or -1 if no such type exists.
        """
        if p < 7:
            return 4
        if p < 16:
            return 8
        if self.arch.startswith(('aarch64', 'power', 'ppc', 'riscv', 's390x', 'sparc')):
            if p <= 20:
                return 16
        else:
            if p < 19:
                return 10
            if p <= 20:
                return 16
        return -1

    def map_selected_real_kind(self, scope, p, r=0, radix=0):
        """
        Return the kind of the smallest real type defined in
        ``iso_fortran_env`` that is able to fulfil the given requirements
        for decimal precision (``p``), decimal exponent range (``r``) and
        radix (``r``).
        """
        byte_kind_map = {b: 'REAL{}'.format(8 * b) for b in [4, 8, 16]}
        kind = self._selected_real_kind(p, r, radix)
        if kind in byte_kind_map:
            kind_name = byte_kind_map[kind]
            self.used_names[kind_name] = sym.Variable(name=kind_name, scope=scope)
            return self.used_names[kind_name]
        return sym.IntLiteral(-1)

    def map_call(self, call, scope):
        if not self.is_selected_kind_call(call):
            return call

        func = getattr(self, 'map_{}'.format(call.name.lower()))
        args = [int(arg) for arg in call.parameters]
        kwargs = {key: int(val) for key, val in call.kw_parameters.items()}

        return func(scope, *args, **kwargs)


def replace_selected_kind(routine):
    """
    Find all uses of ``selected_real_kind`` or ``selected_int_kind`` and
    replace them by their ``iso_fortran_env`` counterparts.

    This inserts imports for all used constants from ``iso_fortran_env``.
    """
    mapper = IsoFortranEnvMapper()

    # Find all selected_x_kind calls in spec and body
    calls = [call for call in FindInlineCalls().visit(routine.ir)
             if mapper.is_selected_kind_call(call)]

    # Need to pick out kinds in Literals explicitly
    calls += [literal.kind for literal in FindLiterals().visit(routine.ir)
              if hasattr(literal, 'kind') and mapper.is_selected_kind_call(literal.kind)]

    map_call = {call: mapper.map_call(call, routine.scope) for call in calls}

    # Flush mapping through spec and body
    routine.spec = SubstituteExpressions(map_call).visit(routine.spec)
    routine.body = SubstituteExpressions(map_call).visit(routine.body)

    # Replace calls and literals hidden in variable kinds and inits
    for variable in routine.variables:
        if variable.type.kind is not None and mapper.is_selected_kind_call(variable.type.kind):
            kind = mapper.map_call(variable.type.kind, routine.scope)
            variable.type = variable.type.clone(kind=kind)
        if variable.type.initial is not None:
            if mapper.is_selected_kind_call(variable.type.initial):
                initial = mapper.map_call(variable.type.initial, routine.scope)
                variable.type = variable.type.clone(initial=initial)
            else:
                init_calls = [literal.kind for literal in FindLiterals().visit(variable.type.initial)
                              if hasattr(literal, 'kind') and mapper.is_selected_kind_call(literal.kind)]
                if init_calls:
                    init_map = {call: mapper.map_call(call, routine.scope) for call in init_calls}
                    initial = SubstituteExpressions(init_map).visit(variable.type.initial)
                    variable.type = variable.type.clone(initial=initial)

    # Make sure iso_fortran_env symbols are imported
    if mapper.used_names:
        for imprt in FindNodes(Import).visit(routine.spec):
            if imprt.module.lower() == 'iso_fortran_env':
                # Update the existing iso_fortran_env import
                imprt_symbols = {str(s).lower() for s in imprt.symbols}
                missing_symbols = set(mapper.used_names.keys()) - imprt_symbols
                symbols = as_tuple(imprt.symbols) + tuple(mapper.used_names[s] for s in missing_symbols)

                # Flush the change through the spec
                routine.spec = Transformer({imprt: Import(imprt.module, symbols=symbols)}).visit(routine.spec)
                break
        else:
            # No iso_fortran_env import present, need to insert a new one
            imprt = Import('iso_fortran_env', symbols=as_tuple(mapper.used_names.values()))
            routine.spec.prepend(imprt)