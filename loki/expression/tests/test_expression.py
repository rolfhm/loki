# (C) Copyright 2018- ECMWF.
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.

from collections import defaultdict
from pathlib import Path
import math
import sys
import pytest
import numpy as np

import pymbolic.primitives as pmbl
import pymbolic.mapper as pmbl_mapper

from loki import (
    Sourcefile, Subroutine, Module, Scope, BasicType,
    SymbolAttributes, DerivedType, ProcedureType
)
from loki.backend import cgen, fgen
from loki.build import jit_compile, clean_test
from loki.expression import (
    symbols as sym, FindVariables, FindExpressions, FindTypedSymbols,
    FindInlineCalls, SubstituteExpressions, AttachScopesMapper, parse_expr
)
from loki.frontend import (
    available_frontends, OFP, OMNI, FP, HAVE_FP, parse_fparser_expression
)
from loki.ir import nodes as ir, FindNodes
from loki.tools import (
    gettempdir, filehash, stdchannel_redirected, stdchannel_is_captured
)

# pylint: disable=too-many-lines


@pytest.fixture(scope='module', name='here')
def fixture_here():
    return Path(__file__).parent


@pytest.mark.parametrize('frontend', available_frontends())
def test_arithmetic(here, frontend):
    """
    Test simple floating point arithmetic expressions (+,-,*,/,**).
    """
    fcode = """
subroutine arithmetic_expr(v1, v2, v3, v4, v5, v6)
  integer, parameter :: jprb = selected_real_kind(13,300)
  real(kind=jprb), intent(in) :: v1, v2, v3, v4
  real(kind=jprb), intent(out) :: v5, v6

  v5 = (v1 + v2) * (v3 - v4)
  v6 = (v1 ** v2) - (v3 / v4)
end subroutine arithmetic_expr
"""
    filepath = here/(f'expression_arithmetic_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='arithmetic_expr')

    v5, v6 = function(2., 3., 10., 5.)
    assert v5 == 25. and v6 == 6.
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_math_intrinsics(here, frontend):
    """
    Test supported math intrinsic functions (min, max, exp, abs, sqrt, log)
    """
    fcode = """
subroutine math_intrinsics(v1, v2, vmin, vmax, vabs, vexp, vsqrt, vlog)
  integer, parameter :: jprb = selected_real_kind(13,300)
  real(kind=jprb), intent(in) :: v1, v2
  real(kind=jprb), intent(out) :: vmin, vmax, vabs, vexp, vsqrt, vlog

  vmin = min(v1, v2)
  vmax = max(v1, v2)
  vabs = abs(v1 - v2)
  vexp = exp(v1 + v2)
  vsqrt = sqrt(v1 + v2)
  vlog = log(v1 + v2)
end subroutine math_intrinsics
"""
    filepath = here/(f'expression_math_intrinsics_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='math_intrinsics')

    vmin, vmax, vabs, vexp, vsqrt, vlog = function(2., 4.)
    assert vmin == 2. and vmax == 4. and vabs == 2.
    assert vexp == np.exp(6.) and vsqrt == np.sqrt(6.) and vlog == np.log(6.)
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_logicals(here, frontend):
    """
    Test logical expressions (and, or, not, tru, false, equal, not nequal).
    """
    fcode = """
subroutine logicals(t, f, vand_t, vand_f, vor_t, vor_f, vnot_t, vnot_f, vtrue, vfalse, veq, vneq)
  logical, intent(in) :: t, f
  logical, intent(out) :: vand_t, vand_f, vor_t, vor_f, vnot_t, vnot_f, vtrue, vfalse, veq, vneq

  vand_t = t .and. t
  vand_f = t .and. f
  vor_t = t .or. f
  vor_f = f .or. f
  vnot_t = .not. f
  vnot_f = .not. t
  vtrue = .true.
  vfalse = .false.
  veq = 3 == 4
  vneq = 3 /= 4
end subroutine logicals
"""
    filepath = here/(f'expression_logicals_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='logicals')

    vand_t, vand_f, vor_t, vor_f, vnot_t, vnot_f, vtrue, vfalse, veq, vneq = function(True, False)
    assert vand_t and vor_t and vnot_t and vtrue and vneq
    assert not(vand_f and vor_f and vnot_f and vfalse and veq)
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_literals(here, frontend):
    """
    Test simple literal values.
    """
    fcode = """
subroutine literals(v1, v2, v3, v4, v5, v6)
  integer, parameter :: jprb = selected_real_kind(13,300)
  real(kind=jprb), intent(out) :: v1, v2, v3
  real(kind=selected_real_kind(13,300)), intent(out) :: v4, v5, v6

  v1 = 66
  v2 = 66.0
  v3 = 2.3
  v4 = 2.4_jprb
  v5 = real(6, kind=jprb) + real(1, kind=selected_real_kind(13,300))
  v6 = real(3.5,jprb)
  v6 = int(3.5)
end subroutine literals
"""
    filepath = here/(f'expression_literals_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='literals')

    v1, v2, v3, v4, v5, v6 = function()
    assert v1 == 66. and v2 == 66. and v4 == 2.4 and v5 == 7.0 and v6 == 3.0
    assert math.isclose(v3, 2.3, abs_tol=1.e-6)
    clean_test(filepath)

    # In addition to value testing, let's make sure
    # that we created the correct expression types
    stmts = FindNodes(ir.Assignment).visit(routine.body)
    assert isinstance(stmts[0].rhs, sym.IntLiteral)
    assert isinstance(stmts[1].rhs, sym.FloatLiteral)
    assert isinstance(stmts[2].rhs, sym.FloatLiteral)
    assert isinstance(stmts[3].rhs, sym.FloatLiteral)
    assert stmts[3].rhs.kind in ['jprb']
    assert isinstance(stmts[4].rhs, sym.Sum)
    for expr in stmts[4].rhs.children:
        assert isinstance(expr, sym.Cast)
        assert str(expr.kind).lower() in ['selected_real_kind(13, 300)', 'jprb']
    assert isinstance(stmts[5].rhs, sym.Cast)
    assert str(stmts[5].rhs.kind).lower() in ['selected_real_kind(13, 300)', 'jprb']
    assert isinstance(stmts[6].rhs, sym.Cast)


@pytest.mark.parametrize('frontend', available_frontends())
def test_boz_literals(here, frontend):
    """
    Test boz literal values.
    """
    fcode = """
subroutine boz_literals(n1, n2, n3, n4, n5, n6)
  integer, intent(out) :: n1, n2, n3, n4, n5, n6

  n1 = int(B'00000')
  n2 = int(b"101010")
  n3 = int(O'737')
  n4 = int(o"007")
  n5 = int(Z'CAFE')
  n6 = int(z"babe")
end subroutine boz_literals
"""
    filepath = here/(f'expression_boz_literals_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='boz_literals')

    n1, n2, n3, n4, n5, n6 = function()
    clean_test(filepath)
    assert n1 == 0 and n2 == 42 and n3 == 479 and n4 == 7 and n5 == 51966 and n6 == 47806

    # In addition to value testing, let's make sure that we created the correct expression types
    if frontend is not OMNI:
        # Note: Omni evaluates BOZ constants, so it creates IntegerLiteral instead...
        # Note: FP converts constants to upper case
        stmts = FindNodes(ir.Assignment).visit(routine.body)

        for stmt in stmts:
            assert isinstance(stmt.rhs.parameters[0], sym.IntrinsicLiteral)

        assert stmts[0].rhs.parameters[0].value == "B'00000'"
        assert stmts[1].rhs.parameters[0].value == 'b"101010"'
        assert stmts[2].rhs.parameters[0].value == "O'737'"
        assert stmts[3].rhs.parameters[0].value == 'o"007"'
        assert stmts[4].rhs.parameters[0].value == "Z'CAFE'"
        assert stmts[5].rhs.parameters[0].value == 'z"babe"'


@pytest.mark.parametrize('frontend', available_frontends(
    skip={OFP: "Not implemented because too stupid in OFP parse tree"})
)
def test_complex_literals(here, frontend):
    """
    Test complex literal values.
    """
    fcode = """
subroutine complex_literals(c1, c2, c3)
  complex, intent(out) :: c1, c2, c3

  c1 = (1.0, -1.0)
  c2 = (3, 2E8)
  c3 = (21_2, 4._8)
end subroutine complex_literals
"""
    filepath = here/(f'expression_complex_literals_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='complex_literals')

    c1, c2, c3 = function()
    clean_test(filepath)
    assert c1 == (1-1j) and c2 == (3+2e8j) and c3 == (21+4j)

    # In addition to value testing, let's make sure that we created the correct expression types
    stmts = FindNodes(ir.Assignment).visit(routine.body)
    assert isinstance(stmts[0].rhs, sym.IntrinsicLiteral) and stmts[0].rhs.value == '(1.0, -1.0)'
    # Note: Here, for inconsistency, FP converts the exponential letter 'e' to lower case...
    assert isinstance(stmts[1].rhs, sym.IntrinsicLiteral) and stmts[1].rhs.value.lower() == '(3, 2e8)'
    assert isinstance(stmts[2].rhs, sym.IntrinsicLiteral)
    try:
        assert stmts[2].rhs.value == '(21_2, 4._8)'
    except AssertionError as excinfo:
        if frontend == OMNI:
            pytest.xfail('OMNI wrongfully assigns the same kind to real and imaginary part')
        raise excinfo


@pytest.mark.parametrize('frontend', available_frontends())
def test_casts(here, frontend):
    """
    Test data type casting expressions.
    """
    fcode = """
subroutine casts(v1, v2, v3, v4, v5)
  integer, parameter :: jprb = selected_real_kind(13,300)
  integer, intent(in) :: v1
  real(kind=jprb), intent(in) :: v2, v3
  real(kind=jprb), intent(out) :: v4, v5

  v4 = real(v1, kind=jprb)  ! Test a plain cast
  v5 = real(v1, kind=jprb) * max(v2, v3)  ! Cast as part of expression
end subroutine casts
"""
    filepath = here/(f'expression_casts_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='casts')

    v4, v5 = function(2, 1., 4.)
    assert v4 == 2. and v5 == 8.
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_logical_array(here, frontend):
    """
    Test logical arrays for masking.
    """
    fcode = """
subroutine logical_array(dim, arr, out)
  integer, parameter :: jprb = selected_real_kind(13,300)
  integer, intent(in) :: dim
  real(kind=jprb), intent(in) :: arr(dim)
  real(kind=jprb), intent(out) :: out(dim)
  logical :: mask(dim)
  integer :: i

  mask(:) = .true.
  mask(1) = .false.
  mask(2) = .false.

  do i=1, dim
    ! Use a logical array and a relational
    ! containing an array in a single expression
    if (mask(i) .and. arr(i) > 1.) then
      out(i) = 3.
    else
      out(i) = 1.
    end if
  end do
end subroutine logical_array
"""
    filepath = here/(f'expression_logical_array_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='logical_array')

    out = np.zeros(6)
    function(6, [0., 2., -1., 3., 0., 2.], out)
    assert (out == [1., 1., 1., 3., 1., 3.]).all()
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends(
    xfail=[(OFP, 'Not implemented')]
))
def test_array_constructor(here, frontend):
    """
    Test various array constructor formats
    """
    fcode = """
subroutine array_constructor(dim, zarr1, zarr2, narr1, narr2, narr3, narr4, narr5)
    implicit none
    integer, intent(in) :: dim
    real(8), intent(inout) :: zarr1(dim+1)
    real(8), intent(inout) :: zarr2(3)
    integer, intent(inout) :: narr1(dim)
    integer, intent(inout) :: narr2(10)
    integer, intent(inout) :: narr3(3)
    integer, intent(inout) :: narr4(2,2)
    integer, intent(inout) :: narr5(10)
    integer :: i

    zarr1 = [ 3.6, (3.6 / I, I = 1, dim) ]
    narr1 = (/ (I, I = 1, DIM) /)
    narr2 = (/1, 0, (I, I = -1, -6, -1), -7, -8 /)
    narr3 = [integer :: 1, 2., 3d0]    ! A default integer array
    zarr2 = [real(8) :: 1, 2, 3._8]  ! A real(8) array
    narr4 = RESHAPE([1,2,3,4], shape=[2,2])
    narr5 = (/(I, I=30, 48, 2)/)
end subroutine array_constructor
    """.strip()

    filepath = here/f'array_constructor_{frontend}.f90'
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='array_constructor')

    literal_lists = [e for e in FindExpressions().visit(routine.body) if isinstance(e, sym.LiteralList)]
    assert len(literal_lists) == 8
    assert {str(l).lower() for l in literal_lists} == {
        '[ 3.6, ( 3.6 / i, i = 1:dim ) ]',
        '[ ( i, i = 1:dim ) ]',
        '[ 1, 0, ( i, i = -1:-6:-1 ), -7, -8 ]',
        '[ <symbolattributes basictype.integer> :: 1, 2., 3d0 ]',
        '[ <symbolattributes basictype.real, kind=8> :: 1, 2, 3._8 ]',
        '[ 1, 2, 3, 4 ]',
        '[ 2, 2 ]',
        '[ ( i, i = 30:48:2 ) ]'
    }

    dim = 13
    zarr1 = np.zeros(dim+1, dtype=np.float64)
    zarr2 = np.zeros(3, dtype=np.float64)
    narr1 = np.zeros(dim, dtype=np.int32)
    narr2 = np.zeros(10, dtype=np.int32)
    narr3 = np.zeros(3, dtype=np.int32)
    narr4 = np.zeros((2, 2), dtype=np.int32, order='F')
    narr5 = np.zeros(10, dtype=np.int32)
    function(dim, zarr1, zarr2, narr1, narr2, narr3, narr4, narr5)

    assert np.isclose(zarr1, ([3.6] + [3.6/(i+1) for i in range(dim)])).all()
    assert np.isclose(zarr2, [1., 2., 3.]).all()
    assert (narr1 == range(1, dim+1)).all()
    assert (narr2 == range(1, -9, -1)).all()
    assert (narr3 == [1, 2, 3]).all()
    assert (narr4 == np.array([[1, 3], [2, 4]], order='F')).all()
    assert (narr5 == range(30, 49, 2)).all()

    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends(xfail=[(OMNI, 'Precedence not honoured')]))
def test_parenthesis(frontend):
    """
    Test explicit parenthesis in provided source code.

    Note, that this test is very niche, as it ensures that mathematically
    insignificant (and hence sort of wrong) bracketing is still honoured.
    The reason is that, if sub-expressions are sufficiently complex,
    this can still cause round-off deviations and hence destroy
    bit-reproducibility.

    Also note, that the OMNI-frontend parser will resolve precedence and
    hence we cannot honour these precedence cases (for now).
    """

    fcode = """
subroutine parenthesis(v1, v2, v3, i)
  integer, parameter :: jprb = selected_real_kind(13,300)
  real(kind=jprb), intent(in) :: v1(:), v2
  real(kind=jprb), intent(out) :: v3
  integer, intent(in) :: i

  v3 = (v1(i-1)**1.23_jprb) * 1.3_jprb + (1_jprb - v2**1.26_jprb)

  v3 = min(5._jprb - 3._jprb*v1(i), 3._jprb*exp(5._jprb*(v1(i) - v2) / (v1(i) - v3)) / 2._jprb*exp(5._jprb*(v1(i) - v2) / (v1(i) -  &
  & v3)))

  v3 = v1(i)*(1.0_jprb / (v2*v3))
end subroutine parenthesis
""".strip()
    routine = Subroutine.from_source(fcode, frontend=frontend)
    stmts = FindNodes(ir.Assignment).visit(routine.body)

    # Check that the reduntant bracket around the minus
    # and the first exponential are still there.
    assert fgen(stmts[0]) == 'v3 = (v1(i - 1)**1.23_jprb)*1.3_jprb + (1_jprb - v2**1.26_jprb)'

    # Now perform a simple substitutions on the expression
    # and make sure we are still parenthesising as we should!
    v2 = [v for v in FindVariables().visit(stmts[0]) if v.name == 'v2'][0]
    v4 = v2.clone(name='v4')
    stmt2 = SubstituteExpressions({v2: v4}).visit(stmts[0])
    assert fgen(stmt2) == 'v3 = (v1(i - 1)**1.23_jprb)*1.3_jprb + (1_jprb - v4**1.26_jprb)'

    # Make sure there are no additional brackets in the exponentials or numerators/denominators
    assert '\n'.join(l.lstrip() for l in fcode.splitlines()[-5:-3]) == fgen(stmts[1]).lower()
    assert fgen(stmts[2]) == fcode.splitlines()[-2].lstrip()


@pytest.mark.parametrize('frontend', available_frontends())
def test_commutativity(frontend):
    """
    Verifies the strict adherence to ordering of commutative terms,
    which can introduce round-off errors if not done conservatively.
    """
    fcode = """
subroutine commutativity(v1, v2, v3)
  integer, parameter :: jprb = selected_real_kind(13,300)
  real(kind=jprb), pointer, intent(in) :: v1(:), v2
  real(kind=jprb), pointer, intent(out) :: v3(:)

  v3(:) = 1._jprb + v2*v1(:) - v2 - v3(:)
end subroutine commutativity
"""
    routine = Subroutine.from_source(fcode, frontend=frontend)
    stmt = FindNodes(ir.Assignment).visit(routine.body)[0]

    assert fgen(stmt) in ('v3(:) = 1.0_jprb + v2*v1(:) - v2 - v3(:)',
                          'v3(:) = 1._jprb + v2*v1(:) - v2 - v3(:)')


@pytest.mark.parametrize('frontend', available_frontends())
def test_index_ranges(frontend):
    """
    Test index range expressions for array accesses.
    """
    fcode = """
subroutine index_ranges(dim, v1, v2, v3, v4, v5)
  integer, parameter :: jprb = selected_real_kind(13,300)
  integer, intent(in) :: dim
  real(kind=jprb), intent(in) :: v1(:), v2(0:), v3(0:4), v4(dim)
  real(kind=jprb), intent(out) :: v5(1:dim)

  v5(:) = v2(1:dim)*v1(::2) - v3(0:4:2)
end subroutine index_ranges
"""
    routine = Subroutine.from_source(fcode, frontend=frontend)
    vmap = routine.variable_map

    assert str(vmap['v1']) == 'v1(:)'
    assert str(vmap['v2']) == 'v2(0:)'
    assert str(vmap['v3']) == 'v3(0:4)'
    # OMNI will insert implicit lower=1 into shape declarations,
    # we simply have to live with it... :(
    assert str(vmap['v4']) == 'v4(dim)' or str(vmap['v4']) == 'v4(1:dim)'
    assert str(vmap['v5']) == 'v5(1:dim)'

    vmap_body = {v.name: v for v in FindVariables().visit(routine.body)}
    assert str(vmap_body['v1']) == 'v1(::2)'
    assert str(vmap_body['v2']) == 'v2(1:dim)'
    assert str(vmap_body['v3']) == 'v3(0:4:2)'
    assert str(vmap_body['v5']) == 'v5(:)'


@pytest.mark.parametrize('frontend', available_frontends())
def test_strings(here, frontend, capsys):
    """
    Test recognition of literal strings.
    """

    # This tests works only if stdout/stderr is not captured by pytest
    if stdchannel_is_captured(capsys):
        pytest.skip('pytest executed without "--show-capture"/"-s"')

    fcode = """
subroutine strings()
  print *, 'Hello world!'
  print *, "42!"
end subroutine strings
"""
    filepath = here/(f'expression_strings_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)

    function = jit_compile(routine, filepath=filepath, objname='strings')
    output_file = gettempdir()/filehash(str(filepath), prefix='', suffix='.log')
    with capsys.disabled():
        with stdchannel_redirected(sys.stdout, output_file):
            function()

    clean_test(filepath)

    with open(output_file, 'r') as f:
        output_str = f.read()

    assert output_str == ' Hello world!\n 42!\n'


@pytest.mark.parametrize('frontend', available_frontends())
def test_very_long_statement(here, frontend):
    """
    Test a long statement with line breaks.
    """
    fcode = """
subroutine very_long_statement(scalar, res)
  integer, intent(in) :: scalar
  integer, intent(out) :: res

  res = 5 * scalar + scalar - scalar + scalar - scalar + (scalar - scalar &
      & + scalar - scalar) - 1 + 2 - 3 + 4 - 5 + 6 - 7 + 8 - (9 + 10      &
        - 9) + 10 - 8 + 7 - 6 + 5 - 4 + 3 - 2 + 1
end subroutine very_long_statement
"""
    filepath = here/(f'expression_very_long_statement_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='very_long_statement')

    scalar = 1
    result = function(scalar)
    assert result == 5
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_output_intrinsics(frontend):
    """
    Some collected intrinsics or other edge cases that failed in cloudsc.
    """
    fcode = """
subroutine output_intrinsics
     integer, parameter :: jprb = selected_real_kind(13,300)
     integer :: numomp, ngptot
     real(kind=jprb) :: tdiff

     numomp = 1
     ngptot = 2
     tdiff = 1.2

1002 format(1x, 2i10, 1x, i4, ' : ', i10)
     write(0, 1002) numomp, ngptot, - 1, int(tdiff * 1000.0_jprb)
end subroutine output_intrinsics
"""
    routine = Subroutine.from_source(fcode, frontend=frontend)

    ref = ['format(1x, 2i10, 1x, i4, \' : \', i10)',
           'write(0, 1002) numomp, ngptot, - 1, int(tdiff * 1000.0_jprb)']

    if frontend == OMNI:
        ref[0] = ref[0].replace("'", '"')
        ref[1] = ref[1].replace('0, 1002', 'unit=0, fmt=1002')
        ref[1] = ref[1].replace(' * ', '*')
        ref[1] = ref[1].replace('- 1', '-1')

    intrinsics = FindNodes(ir.Intrinsic).visit(routine.body)
    assert len(intrinsics) == 2
    assert intrinsics[0].text.lower() == ref[0]
    assert intrinsics[1].text.lower() == ref[1]
    assert fgen(intrinsics).lower() == '{} {}\n{}'.format('1002', *ref)


@pytest.mark.parametrize('frontend', available_frontends())
def test_nested_call_inline_call(here, frontend):
    """
    The purpose of this test is to highlight the differences between calls in expression
    (such as `InlineCall`, `Cast`) and call nodes in the IR.
    """
    fcode = """
subroutine simple_expr(v1, v2, v3, v4, v5, v6)
  ! simple floating point arithmetic
  integer, parameter :: jprb = selected_real_kind(13,300)
  real(kind=jprb), intent(in) :: v1, v2, v3, v4
  real(kind=jprb), intent(out) :: v5, v6

  v5 = (v1 + v2) * (v3 - v4)
  v6 = (v1 ** v2) - (v3 / v4)
end subroutine simple_expr

subroutine very_long_statement(scalar, res)
  integer, intent(in) :: scalar
  integer, intent(out) :: res

  res = 5 * scalar + scalar - scalar + scalar - scalar + (scalar - scalar &
        + scalar - scalar) - 1 + 2 - 3 + 4 - 5 + 6 - 7 + 8 - (9 + 10      &
        - 9) + 10 - 8 + 7 - 6 + 5 - 4 + 3 - 2 + 1
end subroutine very_long_statement

subroutine nested_call_inline_call(v1, v2, v3)
  integer, parameter :: jprb = selected_real_kind(13,300)
  integer, intent(in) :: v1
  real(kind=jprb), intent(out) :: v2
  integer, intent(out) :: v3
  real(kind=jprb) :: tmp1, tmp2

  tmp1 = real(1, kind=jprb)
  call simple_expr(tmp1, abs(-2.0_jprb), 3.0_jprb, real(v1, jprb), v2, tmp2)
  v2 = abs(tmp2 - v2)
  call very_long_statement(int(v2), v3)
end subroutine nested_call_inline_call
"""
    filepath = here/(f'expression_nested_call_inline_call_{frontend}.f90')
    routine = Sourcefile.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='nested_call_inline_call')

    v2, v3 = function(1)
    assert v2 == 8.
    assert v3 == 40
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_no_arg_inline_call(frontend):
    """
    Make sure that no-argument function calls are recognized as such,
    especially when their implementation is unknown.
    """
    fcode_mod = """
module external_mod
  implicit none
contains
  function my_func()
    integer :: my_func
    my_func = 2
  end function my_func
end module external_mod
    """.strip()

    fcode_routine = """
subroutine my_routine(var)
  use external_mod, only: my_func
  implicit none
  integer, intent(out) :: var
  var = my_func()
end subroutine my_routine
    """

    if frontend != OMNI:
        routine = Subroutine.from_source(fcode_routine, frontend=frontend)
        assert routine.symbol_attrs['my_func'].dtype is BasicType.DEFERRED
        assignment = FindNodes(ir.Assignment).visit(routine.body)[0]
        assert assignment.lhs == 'var'
        assert isinstance(assignment.rhs, sym.InlineCall)
        assert isinstance(assignment.rhs.function, sym.DeferredTypeSymbol)

    module = Module.from_source(fcode_mod, frontend=frontend)
    routine = Subroutine.from_source(fcode_routine, frontend=frontend, definitions=module)
    assert isinstance(routine.symbol_attrs['my_func'].dtype, ProcedureType)
    assignment = FindNodes(ir.Assignment).visit(routine.body)[0]
    assert assignment.lhs == 'var'
    assert isinstance(assignment.rhs, sym.InlineCall)
    assert isinstance(assignment.rhs.function, sym.ProcedureSymbol)


@pytest.mark.parametrize('frontend', available_frontends())
def test_inline_call_derived_type_arguments(frontend):
    """
    Check that derived type arguments are correctly represented in
    function calls that include keyword parameters.

    This is due to fparser's habit of sometimes representing function calls
    wrongly as structure constructors, which are handled differently in
    Loki's frontend
    """
    fcode = """
module inline_call_mod
    implicit none

    type mytype
        integer :: val
        integer :: arr(3)
    contains
        procedure :: some_func
    end type mytype

contains

    function check(val, thr) result(is_bad)
        integer, intent(in) :: val
        integer, intent(in), optional :: thr
        integer :: eff_thr
        logical :: is_bad
        if (present(thr)) then
            eff_thr = thr
        else
            eff_thr = 10
        end if
        is_bad = val > thr
    end function check

    function some_func(this) result(is_bad)
        class(mytype), intent(in) :: this
        logical :: is_bad

        is_bad = check(this%val, thr=10) &
            &   .or. check(this%arr(1)) .or. check(val=this%arr(2)) .or. check(this%arr(3))
    end function some_func
end module inline_call_mod
    """.strip()
    module = Module.from_source(fcode, frontend=frontend)
    some_func = module['some_func']
    inline_calls = FindInlineCalls().visit(some_func.body)
    assert len(inline_calls) == 4
    assert {fgen(c) for c in inline_calls} == {
        'check(this%val, thr=10)', 'check(this%arr(1))', 'check(val=this%arr(2))', 'check(this%arr(3))'
    }


@pytest.mark.parametrize('frontend', available_frontends())
def test_character_concat(here, frontend):
    """
    Concatenation operator ``//``
    """
    fcode = """
subroutine character_concat(string)
  character(10) :: tmp_str1, tmp_str2
  character(len=12), intent(out) :: string

  tmp_str1 = "Hel" // "lo"
  tmp_str2 = "wor" // "l" // "d"
  string = trim(tmp_str1) // " " // trim(tmp_str2)
  string = trim(string) // "!"
end subroutine character_concat
"""
    filepath = here/(f'expression_character_concat_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='character_concat')

    result = function()
    assert result == b'Hello world!'
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_masked_statements(here, frontend):
    """
    Masked statements (WHERE(...) ... [ELSEWHERE ...] ENDWHERE)
    """
    fcode = """
subroutine expression_masked_statements(length, vec1, vec2, vec3)
  integer, parameter :: jprb = selected_real_kind(13,300)
  integer, intent(in) :: length
  real(kind=jprb), intent(inout), dimension(length) :: vec1, vec2, vec3

  where (vec1(:) > 5.0_jprb)
    vec1(:) = 7.0_jprb
    vec1(:) = 5.0_jprb
  endwhere

  where (vec2(:) < -0.d1)
    vec2(:) = -1.0_jprb
  elsewhere (vec2(:) > 0.d1)
    vec2(:) = 1.0_jprb
  elsewhere
    vec2(:) = 0.0_jprb
  endwhere

  where (0.0_jprb < vec3(:) .and. vec3(:) < 3.0_jprb) vec3(:) = 1.0_jprb
end subroutine expression_masked_statements
"""
    routine = Subroutine.from_source(fcode, frontend=frontend)
    filepath = here/(f'{routine.name}_{frontend}.f90')
    function = jit_compile(routine, filepath=filepath, objname=routine.name)

    # Reference solution
    length = 11
    ref1 = np.append(np.arange(0, 6, dtype=np.float64),
                     5 * np.ones(length - 6, dtype=np.float64))
    ref2 = np.append(np.append(-1 *np.ones(5, dtype=np.float64), 0.0),
                     np.ones(5, dtype=np.float64))
    ref3 = np.append(np.arange(-2, 1, dtype=np.float64), np.ones(2, dtype=np.float64))
    ref3 = np.append(ref3, np.arange(3, length - 2, dtype=np.float64))

    vec1 = np.arange(0, length, dtype=np.float64)
    vec2 = np.arange(-5, length - 5, dtype=np.float64)
    vec3 = np.arange(-2, length - 2, dtype=np.float64)
    function(length, vec1, vec2, vec3)
    assert np.all(ref1 == vec1)
    assert np.all(ref2 == vec2)
    assert np.all(ref3 == vec3)
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends(xfail=[
    (OFP, 'Current implementation does not handle nested where constructs')
]))
def test_masked_statements_nested(here, frontend):
    """
    Nested masked statements (WHERE(...) ... [ELSEWHERE ...] ENDWHERE)
    """
    fcode = """
subroutine expression_nested_masked_statements(length, vec1)
    integer, parameter :: jprb = selected_real_kind(13,300)
    integer, intent(in) :: length
    real(kind=jprb), intent(inout), dimension(length) :: vec1

    where (vec1(:) >= 4.0_jprb)
        where (vec1(:) > 6.0_jprb)
            vec1(:) = 6.0_jprb
        elsewhere
            vec1(:) = 4.0_jprb
        endwhere
    elsewhere
        where (vec1(:) < 2.0_jprb)
            vec1(:) = 0.0_jprb
        elsewhere
            vec1(:) = 2.0_jprb
        endwhere
    endwhere
end subroutine expression_nested_masked_statements
"""
    routine = Subroutine.from_source(fcode, frontend=frontend)
    filepath = here/(f'{routine.name}_{frontend}.f90')
    function = jit_compile(routine, filepath=filepath, objname=routine.name)

    # Reference solution
    length = 11
    vec1 = np.arange(0, length, dtype=np.float64)
    ref1 = np.zeros(length, dtype=np.float64)
    ref1[vec1 >= 4.0] = 4.0
    ref1[vec1 > 6.0] = 6.0
    ref1[vec1 < 4.0] = 2.0
    ref1[vec1 < 2.0] = 0.0
    function(length, vec1)
    assert np.all(ref1 == vec1)
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends(xfail=[
    (OMNI, 'Not implemented'), (FP, 'Not implemented')
]))
def test_data_declaration(here, frontend):
    """
    Variable initialization with DATA statements
    """
    fcode = """
subroutine data_declaration(data_out)
  implicit none
  integer, dimension(5, 4), intent(out) :: data_out
  integer, dimension(5, 4) :: data1, data2
  integer, dimension(3) :: data3
  integer :: i, j

  data data1 /20*5/

  data ((data2(i,j), i=1,5), j=1,4) /20*3/

  data data3(1), data3(3), data3(2) /1, 2, 3/

  data_out(:,:) = data1(:,:) + data2(:,:)
  data_out(1:3,1) = data3
end subroutine data_declaration
"""
    filepath = here/(f'expression_data_declaration_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='data_declaration')

    expected = np.ones(shape=(5, 4), dtype=np.int32, order='F') * 8
    expected[[0, 1, 2], 0] = [1, 3, 2]
    result = np.zeros(shape=(5, 4), dtype=np.int32, order='F')
    function(result)
    assert np.all(result == expected)
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_pointer_nullify(here, frontend):
    """
    POINTERS and their nullification via '=> NULL()'
    """
    fcode = """
subroutine pointer_nullify()
  implicit none
  character(len=64), dimension(:), pointer :: charp => NULL()
  character(len=64), pointer :: pp => NULL()
  allocate(charp(3))
  charp(:) = "_ptr_"
  pp => charp(1)
  pp = "_other_ptr_"
  nullify(pp)
  deallocate(charp)
  charp => NULL()
end subroutine pointer_nullify
"""
    filepath = here/(f'expression_pointer_nullify_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)

    assert np.all(v.type.pointer for v in routine.variables)
    assert np.all(isinstance(v.initial, sym.InlineCall) and v.type.initial.name.lower() == 'null'
                  for v in routine.variables)
    nullify_stmts = FindNodes(ir.Nullify).visit(routine.body)
    assert len(nullify_stmts) == 1
    assert nullify_stmts[0].variables[0].name == 'pp'
    assert [stmt.ptr for stmt in FindNodes(ir.Assignment).visit(routine.body)].count(True) == 2

    # Execute the generated identity (to verify it is valid Fortran)
    function = jit_compile(routine, filepath=filepath, objname='pointer_nullify')
    function()
    clean_test(filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_parameter_stmt(here, frontend):
    """
    PARAMETER(...) statement
    """
    fcode = """
subroutine parameter_stmt(out1)
  implicit none
  integer, parameter :: jprb = selected_real_kind(13,300)
  real(kind=jprb) :: param
  parameter(param=2.0)
  real(kind=jprb), intent(out) :: out1

  out1 = param
end subroutine parameter_stmt
"""
    filepath = here/(f'expression_parameter_stmt_{frontend}.f90')
    routine = Subroutine.from_source(fcode, frontend=frontend)
    function = jit_compile(routine, filepath=filepath, objname='parameter_stmt')

    out1 = function()
    assert out1 == 2.0
    clean_test(filepath)


def test_string_compare():
    """
    Test that we can identify symbols and expressions by equivalent strings.

    Note that this only captures comparsion of a canonical string representation,
    not full symbolic equivalence.
    """
    # Utility objects for manual expression creation
    scope = Scope()
    type_int = SymbolAttributes(dtype=BasicType.INTEGER)
    type_real = SymbolAttributes(dtype=BasicType.REAL)

    i = sym.Variable(name='i', scope=scope, type=type_int)
    j = sym.Variable(name='j', scope=scope, type=type_int)

    # Test a scalar variable
    u = sym.Variable(name='u', scope=scope, type=SymbolAttributes(dtype=BasicType.REAL))
    assert all(u == exp for exp in ['u', 'U', 'u ', 'U '])
    assert not all(u == exp for exp in ['u()', '_u', 'U()', '_U'])

    # Test an array variable
    v = sym.Variable(name='v', dimensions=(i, j), scope=scope, type=type_real)
    assert all(v == exp for exp in ['v(i,j)', 'v(i, j)', 'v (i , j)', 'V(i,j)', 'V(I, J)'])
    assert not all(v == exp for exp in ['v(i,j())', 'v(i,_j)', '_V(i,j)'])

    # Test a standard array dimension range
    r = sym.RangeIndex(children=(i, j))
    w = sym.Variable(name='w', dimensions=(r,), scope=scope, type=type_real)
    assert all(w == exp for exp in ['w(i:j)', 'w (i : j)', 'W(i:J)', ' w( I:j)'])

    # Test simple arithmetic expressions
    assert all(sym.Sum((i, u)) == exp for exp in ['i+u', 'i + u', 'i +  U', ' I + u'])
    assert all(sym.Product((i, u)) == exp for exp in ['i*u', 'i * u', 'i *  U', ' I * u'])
    assert all(sym.Quotient(i, u) == exp for exp in ['i/u', 'i / u', 'i /  U', ' I / u'])
    assert all(sym.Power(i, u) == exp for exp in ['i**u', 'i ** u', 'i **  U', ' I ** u'])
    assert all(sym.Comparison(i, '==', u) == exp for exp in ['i==u', 'i == u', 'i ==  U', ' I == u'])
    assert all(sym.LogicalAnd((i, u)) == exp for exp in ['i AND u', 'i and u', 'i and  U', ' I and u'])
    assert all(sym.LogicalOr((i, u)) == exp for exp in ['i OR u', 'i or u', 'i or  U', ' I oR u'])
    assert all(sym.LogicalNot(u) == exp for exp in ['not u', ' nOt u', 'not  U', ' noT u'])

    # Test literal behaviour
    assert sym.Literal(41) == 41
    assert sym.Literal(41) == '41'
    assert sym.Literal(41) != sym.Literal(41, kind='jpim')
    assert sym.Literal(66.6) == 66.6
    assert sym.Literal(66.6) == '66.6'
    assert sym.Literal(66.6) != sym.Literal(66.6, kind='jprb')
    assert sym.Literal('u') == 'u'
    assert sym.Literal('u') != 'U'
    assert sym.Literal('u') != u  # The `Variable(name='u', ...) from above
    assert sym.Literal('.TrUe.') == 'true'
    # Specific test for constructor checks
    assert sym.LogicLiteral(value=True) == 'true'


@pytest.mark.parametrize('expr, string, ref', [
    ('a + 1', 'a', True),
    ('u(a)', 'a', True),
    ('u(a + 1)', 'a', True),
    ('u(a + 1) + 2', 'u(a + 1)', True),
    ('ansatz(a + 1)', 'a', True),
    ('ansatz(b + 1)', 'a', False),  # Ensure no false positives
])
@pytest.mark.parametrize('parse', (
    parse_expr,
    pytest.param(parse_fparser_expression,
        marks=pytest.mark.skipif(not HAVE_FP, reason='parse_fparser_expression not available!'))
))
def test_subexpression_match(parse, expr, string, ref):
    """
    Test that we can identify individual symbols or sub-expressions in
    expressions via canonical string matching.
    """
    scope = Scope()
    expr = parse(expr, scope)
    assert (string in expr) == ref


@pytest.mark.parametrize('source, ref', [
    ('1 + 1', '1 + 1'),
    ('1+2+3+4', '1 + 2 + 3 + 4'),
    ('5*4 - 3*2 - 1', '5*4 - 3*2 - 1'),
    ('1*(2 + 3)', '1*(2 + 3)'),
    ('5*a +3*7**5 - 4/b', '5*a + 3*7**5 - 4 / b'),
    ('5 + (4 + 3) - (2*1)', '5 + (4 + 3) - (2*1)'),
    ('a*(b*(c+(d+e)))', 'a*(b*(c + (d + e)))'),
])
@pytest.mark.parametrize('parse', (
    parse_expr,
    pytest.param(parse_fparser_expression,
        marks=pytest.mark.skipif(not HAVE_FP, reason='parse_fparser_expression not available!'))
))
def test_parse_expression(parse, source, ref):
    """
    Test the utility function that parses simple expressions.
    """
    scope = Scope()
    ir = parse(source, scope)  # pylint: disable=redefined-outer-name
    assert isinstance(ir, pmbl.Expression)
    assert str(ir) == ref


@pytest.mark.parametrize('kwargs,reftype', [
    ({}, sym.DeferredTypeSymbol),
    ({'type': SymbolAttributes(BasicType.DEFERRED)}, sym.DeferredTypeSymbol),
    ({'type': SymbolAttributes(BasicType.INTEGER)}, sym.Scalar),
    ({'type': SymbolAttributes(BasicType.REAL)}, sym.Scalar),
    ({'type': SymbolAttributes(DerivedType('t'))}, sym.Scalar),
    ({'type': SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(3),))}, sym.Array),
    ({'type': SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(3),)),
      'dimensions': (sym.Literal(1),)}, sym.Array),
    ({'type': SymbolAttributes(BasicType.INTEGER), 'dimensions': (sym.Literal(1),)}, sym.Array),
    ({'type': SymbolAttributes(BasicType.DEFERRED), 'dimensions': (sym.Literal(1),)}, sym.Array),
    ({'type': SymbolAttributes(ProcedureType('routine'))}, sym.ProcedureSymbol),
])
def test_variable_factory(kwargs, reftype):
    """
    Test the factory class :any:`Variable` and the dispatch to correct classes.
    """
    scope = Scope()
    assert isinstance(sym.Variable(name='var', scope=scope, **kwargs), reftype)


def test_variable_factory_invalid():
    """
    Test invalid variable instantiations
    """
    with pytest.raises(KeyError):
        _ = sym.Variable()


@pytest.mark.parametrize('initype,inireftype,newtype,newreftype', [
    # From deferred type to other type
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(BasicType.INTEGER), sym.Scalar),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(BasicType.REAL), sym.Scalar),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(DerivedType('t')), sym.Scalar),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(4),)), sym.Array),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(ProcedureType('routine')), sym.ProcedureSymbol),
    (None, sym.DeferredTypeSymbol, SymbolAttributes(BasicType.INTEGER), sym.Scalar),
    # From Scalar to other type
    (SymbolAttributes(BasicType.INTEGER), sym.Scalar,
     SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol),
    (SymbolAttributes(BasicType.INTEGER), sym.Scalar,
     SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(3),)), sym.Array),
    (SymbolAttributes(BasicType.INTEGER), sym.Scalar,
     SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol),
    # From Array to other type
    (SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(4),)), sym.Array,
     SymbolAttributes(BasicType.INTEGER), sym.Scalar),
    (SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(4),)), sym.Array,
     SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol),
    (SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(4),)), sym.Array,
     SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol),
    # From ProcedureSymbol to other type
    (SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol,
     SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol),
    (SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol,
     SymbolAttributes(BasicType.INTEGER), sym.Scalar),
    (SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol,
     SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(5),)), sym.Array),
])
def test_variable_rebuild(initype, inireftype, newtype, newreftype):
    """
    Test that rebuilding a variable object changes class according to symmbol type
    """
    scope = Scope()
    var = sym.Variable(name='var', scope=scope, type=initype)
    assert isinstance(var, inireftype)
    assert 'var' in scope.symbol_attrs
    scope.symbol_attrs['var'] = newtype
    assert isinstance(var, inireftype)
    var = var.clone()  # pylint: disable=no-member
    assert isinstance(var, newreftype)


@pytest.mark.parametrize('initype,inireftype,newtype,newreftype', [
    # From deferred type to other type
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(BasicType.INTEGER), sym.Scalar),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(BasicType.REAL), sym.Scalar),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(DerivedType('t')), sym.Scalar),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(4),)), sym.Array),
    (SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol,
     SymbolAttributes(ProcedureType('routine')), sym.ProcedureSymbol),
    (None, sym.DeferredTypeSymbol, SymbolAttributes(BasicType.INTEGER), sym.Scalar),
    # From Scalar to other type
    (SymbolAttributes(BasicType.INTEGER), sym.Scalar,
     SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol),
    (SymbolAttributes(BasicType.INTEGER), sym.Scalar,
     SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(3),)), sym.Array),
    (SymbolAttributes(BasicType.INTEGER), sym.Scalar,
     SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol),
    # From Array to other type
    (SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(4),)), sym.Array,
     SymbolAttributes(BasicType.INTEGER), sym.Scalar),
    (SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(4),)), sym.Array,
     SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol),
    (SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(4),)), sym.Array,
     SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol),
    # From ProcedureSymbol to other type
    (SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol,
     SymbolAttributes(BasicType.DEFERRED), sym.DeferredTypeSymbol),
    (SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol,
     SymbolAttributes(BasicType.INTEGER), sym.Scalar),
    (SymbolAttributes(ProcedureType('foo')), sym.ProcedureSymbol,
     SymbolAttributes(BasicType.INTEGER, shape=(sym.Literal(5),)), sym.Array),
])
def test_variable_clone_class(initype, inireftype, newtype, newreftype):
    """
    Test that cloning a variable object changes class according to symbol type
    """
    scope = Scope()
    var = sym.Variable(name='var', scope=scope, type=initype)
    assert isinstance(var, inireftype)
    assert 'var' in scope.symbol_attrs
    var = var.clone(type=newtype)  # pylint: disable=no-member
    assert isinstance(var, newreftype)

@pytest.mark.parametrize('initype,newtype,reftype', [
    # Preserve existing type info if type=None is given
    (SymbolAttributes(BasicType.REAL), None, SymbolAttributes(BasicType.REAL)),
    (SymbolAttributes(BasicType.INTEGER), None, SymbolAttributes(BasicType.INTEGER)),
    (SymbolAttributes(BasicType.DEFERRED), None, SymbolAttributes(BasicType.DEFERRED)),
    (SymbolAttributes(BasicType.DEFERRED, intent='in'), None,
     SymbolAttributes(BasicType.DEFERRED, intent='in')),
    # Update from deferred to known type
    (SymbolAttributes(BasicType.DEFERRED), SymbolAttributes(BasicType.INTEGER),
     SymbolAttributes(BasicType.INTEGER)),
    (SymbolAttributes(BasicType.DEFERRED), SymbolAttributes(BasicType.REAL),
     SymbolAttributes(BasicType.REAL)),
    (SymbolAttributes(BasicType.DEFERRED), SymbolAttributes(BasicType.DEFERRED, intent='in'),
     SymbolAttributes(BasicType.DEFERRED, intent='in')),  # Special case: Add attribute only
    # Invalidate type by setting to DEFERRED
    (SymbolAttributes(BasicType.INTEGER), SymbolAttributes(BasicType.DEFERRED),
     SymbolAttributes(BasicType.DEFERRED)),
    (SymbolAttributes(BasicType.REAL), SymbolAttributes(BasicType.DEFERRED),
     SymbolAttributes(BasicType.DEFERRED)),
    (SymbolAttributes(BasicType.DEFERRED, intent='in'), SymbolAttributes(BasicType.DEFERRED),
     SymbolAttributes(BasicType.DEFERRED)),
])
def test_variable_clone_type(initype, newtype, reftype):
    """
    Test type updates are handled as expected and types are never ``None``.
    """
    scope = Scope()
    var = sym.Variable(name='var', scope=scope, type=initype)
    assert 'var' in scope.symbol_attrs
    new = var.clone(type=newtype)  # pylint: disable=no-member
    assert new.type == reftype


def test_variable_without_scope():
    """
    Test that creating variables without scope works and scopes can be
    attached and detached
    """
    # pylint: disable=no-member
    # Create a plain variable without type or scope
    var = sym.Variable(name='var')
    assert isinstance(var, sym.DeferredTypeSymbol)
    assert var.type and var.type.dtype is BasicType.DEFERRED
    # Attach a scope with a data type for this variable
    scope = Scope()
    scope.symbol_attrs['var'] = SymbolAttributes(BasicType.INTEGER)
    assert isinstance(var, sym.DeferredTypeSymbol)
    assert var.type and var.type.dtype is BasicType.DEFERRED
    var = var.clone(scope=scope)
    assert var.scope is scope
    assert isinstance(var, sym.Scalar)
    assert var.type.dtype is BasicType.INTEGER
    # Change the data type via constructor
    var = var.clone(type=SymbolAttributes(BasicType.REAL))
    assert isinstance(var, sym.Scalar)
    assert var.type.dtype is BasicType.REAL
    assert scope.symbol_attrs['var'].dtype is BasicType.REAL
    # Detach the scope (type remains)
    var = var.clone(scope=None)
    assert var.scope is None
    assert isinstance(var, sym.Scalar)
    assert var.type.dtype is BasicType.REAL
    assert scope.symbol_attrs['var'].dtype is BasicType.REAL
    # Assign a data type locally
    var = var.clone(type=SymbolAttributes(BasicType.LOGICAL))
    assert var.scope is None
    assert isinstance(var, sym.Scalar)
    assert var.type.dtype is BasicType.LOGICAL
    assert scope.symbol_attrs['var'].dtype is BasicType.REAL
    # Re-attach the scope without specifying type
    var = var.clone(scope=scope, type=None)
    assert var.scope is scope
    assert isinstance(var, sym.Scalar)
    assert var.type.dtype is BasicType.REAL
    assert scope.symbol_attrs['var'].dtype is BasicType.REAL
    # Detach the scope and specify new type
    var = var.clone(scope=None, type=SymbolAttributes(BasicType.LOGICAL))
    assert var.scope is None
    assert isinstance(var, sym.Scalar)
    assert var.type.dtype is BasicType.LOGICAL
    assert scope.symbol_attrs['var'].dtype is BasicType.REAL
    # Rescope (doesn't overwrite scope-stored type with local type)
    rescoped_var = var.rescope(scope)
    assert rescoped_var.scope is scope
    assert isinstance(rescoped_var, sym.Scalar)
    assert rescoped_var.type.dtype is BasicType.REAL
    assert scope.symbol_attrs['var'].dtype is BasicType.REAL
    # Re-attach the scope (uses scope-stored type over local type)
    var = var.clone(scope=scope)
    assert var.scope is scope
    assert isinstance(var, sym.Scalar)
    assert var.type.dtype is BasicType.REAL
    assert scope.symbol_attrs['var'].dtype is BasicType.REAL


@pytest.mark.parametrize('expr', [
    ('1.8 - 3.E-03*ztp1'),
    ('1.8 - 0.003*ztp1'),
    ('(a / b) + 3.0_jprb'),
    ('a / b*3.0_jprb'),
    ('-5*3 + (-(5*3))'),
    ('5 + (-1)'),
    ('5 - 1')
])
@pytest.mark.parametrize('parse', (
    parse_expr,
    pytest.param(parse_fparser_expression,
        marks=pytest.mark.skipif(not HAVE_FP, reason='parse_fparser_expression not available!'))
))
def test_standalone_expr_parenthesis(expr, parse):
    scope = Scope()
    ir = parse(expr, scope)  # pylint: disable=redefined-outer-name
    assert isinstance(ir, pmbl.Expression)
    assert fgen(ir) == expr


@pytest.mark.parametrize('parse', (
    parse_expr,
    pytest.param(parse_fparser_expression,
        marks=pytest.mark.skipif(not HAVE_FP, reason='parse_fparser_expression not available!'))
))
def test_array_to_inline_call_rescope(parse):
    """
    Test a mechanism that can convert arrays to procedure calls, to mop up
    broken frontend behaviour wrongly classifying inline calls as array subscripts
    """
    # Parse the expression, which fparser will interpret as an array
    scope = Scope()
    expr = parse('FLUX%OUT_OF_PHYSICAL_BOUNDS(KIDIA, KFDIA)', scope=scope)
    assert isinstance(expr, sym.Array)

    # Detach the expression from the scope and update the type information in the scope
    expr = expr.clone(scope=None)
    return_type = SymbolAttributes(BasicType.INTEGER)
    proc_type = ProcedureType('out_of_physical_bounds', is_function=True, return_type=return_type)
    scope.symbol_attrs['flux%out_of_physical_bounds'] = SymbolAttributes(proc_type)

    # Re-attach the scope to trigger the rescoping (and symbol rebuild)
    expr = AttachScopesMapper()(expr, scope=scope)
    assert isinstance(expr, sym.InlineCall)
    assert expr.function.type.dtype is proc_type
    assert expr.function == 'flux%out_of_physical_bounds'
    assert expr.parameters == ('kidia', 'kfdia')


@pytest.mark.parametrize('frontend', available_frontends())
def test_recursive_substitution(frontend):
    """
    Test expression substitution where the substitution key is included
    in the replacement
    """
    fcode = """
subroutine my_routine(var, n)
    real, intent(inout) :: var(:)
    integer, intent(in) :: n
    integer j
    do j=1,n
        var(j) = 1.
    end do
end subroutine my_routine
    """.strip()

    routine = Subroutine.from_source(fcode, frontend=frontend)
    assignment = FindNodes(ir.Assignment).visit(routine.body)[0]
    assert assignment.lhs == 'var(j)'

    # Replace Array subscript by j+1
    j = routine.variable_map['j']
    expr_map = {j: sym.Sum((j, sym.Literal(1)))}
    assert j in FindVariables().visit(list(expr_map.values()))
    routine.body = SubstituteExpressions(expr_map).visit(routine.body)
    assignment = FindNodes(ir.Assignment).visit(routine.body)[0]
    assert assignment.lhs == 'var(j + 1)'


def test_nested_derived_type_substitution():
    """
    Test that :any:`SubstituteExpressions` can properly replace scalar
    parents when type is not changed
    """

    type_int = SymbolAttributes(dtype=BasicType.INTEGER)
    original = sym.Scalar(name='ydphy3')
    expr = sym.Scalar(name='n_spband', type=type_int, parent=sym.Scalar(name='ydphy3'))
    replace = sym.Scalar(name='yrphy3', parent=sym.Scalar(name='ydml_phy_mf'))
    new_expr = SubstituteExpressions({original:replace}).visit(expr)

    assert fgen(new_expr) == 'ydml_phy_mf%yrphy3%n_spband'


@pytest.mark.parametrize('frontend', available_frontends())
def test_variable_in_declaration_initializer(frontend):
    """
    Check correct handling of cases where the variable appears
    in the initializer expression (i.e. no infinite recursion)
    """
    fcode = """
subroutine some_routine(var)
implicit none
INTEGER, PARAMETER :: JPRB = SELECTED_REAL_KIND(13,300)
REAL(KIND=JPRB), PARAMETER :: ZEXPLIMIT = LOG(HUGE(ZEXPLIMIT))
real(kind=jprb), intent(inout) :: var
var = var + ZEXPLIMIT
end subroutine some_routine
    """.strip()

    def _check(routine_):
        # A few sanity checks
        assert 'zexplimit' in routine_.variable_map
        zexplimit = routine_.variable_map['zexplimit']
        assert zexplimit.scope is routine_
        # Now let's take a closer look at the initializer expression
        assert 'zexplimit' in str(zexplimit.type.initial).lower()
        variables = FindVariables().visit(zexplimit.type.initial)
        assert 'zexplimit' in variables
        assert variables[variables.index('zexplimit')].scope is routine_

    routine = Subroutine.from_source(fcode, frontend=frontend)
    _check(routine)
    # Make sure that's still true when doing another scope attachment
    routine.rescope_symbols()
    _check(routine)


@pytest.mark.parametrize('frontend', available_frontends())
def test_variable_in_dimensions(frontend):
    """
    Check correct handling of cases where the variable appears in the
    dimensions expression of the same variable (i.e. do not cause
    infinite recursion)
    """
    fcode = """
module some_mod
    implicit none

    type multi_level
        real, allocatable :: data(:, :)
    end type multi_level
contains
    subroutine some_routine(levels, num_levels)
        type(multi_level), intent(inout) :: levels(:)
        integer, intent(in) :: num_levels
        integer jscale

        do jscale = 2,num_levels
            allocate(levels(jscale)%data(size(levels(jscale-1)%data,1), size(levels(jscale-1)%data,2)))
        end do
    end subroutine some_routine
end module some_mod
    """.strip()

    module = Module.from_source(fcode, frontend=frontend)
    routine = module['some_routine']
    assert 'levels%data' in routine.symbol_attrs
    shape = routine.symbol_attrs['levels%data'].shape
    assert len(shape) == 2
    for i, dim in enumerate(shape):
        assert isinstance(dim, sym.InlineCall)
        assert str(dim).lower() == f'size(levels(jscale - 1)%data, {i+1})'


def test_expression_container_matching():
    """
    Tests how different expression types match as keys in different
    containers, with use of raw expressions and string equivalence.
    """
    scope = Scope()
    t_real = SymbolAttributes(BasicType.REAL)
    t_int = SymbolAttributes(BasicType.INTEGER)

    i = sym.Variable(name='i', scope=scope, type=t_int)
    a = sym.Variable(name='a', scope=scope, type=t_real)
    b = sym.Variable(name='b', scope=scope, type=t_real, dimensions=(i,))

    # Test for simple containment of scalars
    assert a in (a, b)
    assert a in [a, b]
    assert a in {a, b}
    assert a in {a: b}
    assert a in defaultdict(list, ((a, [b]),))

    # Test for simple containment of scalars against strings
    assert a == 'a'
    assert a in ('a', 'b(i)')
    assert a in ['a', 'b(i)']
    assert a in {'a', 'b(i)'}
    assert a in {'a': 'b(i)'}
    assert a in defaultdict(list, (('a', ['b(i)']),))

    # Test for simple containment of arrays against strings
    assert b == 'b(i)'
    assert b in ('b(i)', 'a')
    assert b in ['b(i)', 'a']
    assert b in {'b(i)', 'a'}
    assert b in {'b(i)': 'a'}
    assert b in defaultdict(list, (('b(i)', ['a']),))

    # Test for simple containment of strings indices against arrays
    assert 'b(i)' in (b, a)
    assert 'b(i)' in [b, a]
    assert 'b(i)' in {b, a}
    assert 'b(i)' in {b: a}
    assert 'b(i)' in defaultdict(list, ((b, [a]),))


@pytest.mark.parametrize('frontend', available_frontends())
def test_expression_finder_retrieval_function(frontend):
    """
    Verify that expression finder visitors work as intended and remain
    functional if re-used
    """
    fcode = """
module some_mod
    implicit none
contains
    function some_func() result(ret)
        integer :: ret
        ret = 1
    end function some_func

    subroutine other_routine
        integer :: var, tmp
        var = 5 + some_func()
    end subroutine other_routine
end module some_mod
    """.strip()

    source = Sourcefile.from_source(fcode, frontend=frontend)

    expected_ts = {'var', 'some_func'}
    expected_vars = ('var',)

    # Instantiate the first expression finder and make sure it works as expected
    find_ts = FindTypedSymbols()
    assert find_ts.visit(source['other_routine'].body) == expected_ts

    # Verify that it works also on a repeated invocation
    assert find_ts.visit(source['other_routine'].body) == expected_ts

    # Instantiate the second expression finder and make sure it works as expected
    find_vars = FindVariables(unique=False)
    assert find_vars.visit(source['other_routine'].body) == expected_vars

    # Make sure the first expression finder still works
    assert find_ts.visit(source['other_routine'].body) == expected_ts


@pytest.mark.parametrize('frontend', available_frontends())
def test_expression_c_de_reference(frontend):
    """
    Verify that ```Reference`` and ``Dereference`` work as expected.
    Thus, being ignored by Fortran-like backends but not by C-like
    backends.
    """
    fcode = """
subroutine some_routine()
implicit none
  integer :: var_reference
  integer :: var_dereference

  var_reference = 1
  var_dereference = 2
end subroutine some_routine
    """.strip()

    routine = Subroutine.from_source(fcode, frontend=frontend)
    var_map = {
        routine.variable_map['var_reference']: sym.Reference(routine.variable_map['var_reference']),
        routine.variable_map['var_dereference']: sym.Dereference(routine.variable_map['var_dereference'])
    }
    routine.body = SubstituteExpressions(var_map).visit(routine.body)

    f_str = fgen(routine).replace(' ', '')
    assert 'var_reference=1' in f_str
    assert 'var_dereference=2' in f_str
    assert '*' not in f_str
    assert '&' not in f_str

    c_str = cgen(routine).replace(' ', '')
    assert '(&var_reference)=1' in c_str
    assert '(*var_dereference)=2' in c_str

    # now test processing in mappers (by renaming variables being "De/Referenced")
    var_reference = routine.variable_map['var_reference']
    var_dereference = routine.variable_map['var_dereference']
    var_map = {var_reference: var_reference.clone(name='renamed_var_reference'),
            var_dereference: var_dereference.clone(name='renamed_var_dereference')}
    routine.spec = SubstituteExpressions(var_map).visit(routine.spec)
    routine.body = SubstituteExpressions(var_map).visit(routine.body)

    f_str = fgen(routine).replace(' ', '')
    assert 'renamed_var_reference=1' in f_str
    assert 'renamed_var_dereference=2' in f_str
    assert '*' not in f_str
    assert '&' not in f_str

    c_str = cgen(routine).replace(' ', '')
    assert '(&renamed_var_reference)=1' in c_str
    assert '(*renamed_var_dereference)=2' in c_str


@pytest.mark.parametrize('expr', [
    'a', 'a%b', 'a%b%c', 'a%b%c%d', 'a%b%c%d%e'
])
def test_typebound_resolution(expr):
    """
    Test that type-bound variables can be correctly resolved
    """

    scope = Scope()
    name_parts = expr.split('%', maxsplit=1)
    var = sym.Variable(name=name_parts[0], scope=scope)

    if len(name_parts) > 1:
        var = var.get_derived_type_member(name_parts[1]) # pylint: disable=no-member

    assert var == expr
    assert var.scope == scope


@pytest.mark.parametrize('frontend', available_frontends(
    skip={OMNI: "OMNI fails on missing module"}
))
def test_typebound_resolution_type_info(frontend):
    fcode = """
module typebound_resolution_type_info_mod
    use some_mod, only: tt
    implicit none
    type t_a
        logical :: a
    end type t_a

    type t_b
        type(t_a) :: b_a
        integer :: b
    end type t_b

    type t_c
        type(t_b) :: c_b
        real :: c
    end type t_c
contains
    subroutine sub ()
        type(t_c) :: var_c
        type(tt) :: var_tt
    end subroutine sub
end module typebound_resolution_type_info_mod
    """.strip()

    module = Module.from_source(fcode, frontend=frontend)

    sub = module['sub']
    var_c = sub.variable_map['var_c']
    var_tt = sub.variable_map['var_tt']

    t_a = module['t_a']
    t_b = module['t_b']

    var_c_to_try = {
        'c': BasicType.REAL,
        'c_b': t_b.dtype,
        'c_b%b': BasicType.INTEGER,
        'c_b%b_a': t_a.dtype,
        'c_b%b_a%a': BasicType.LOGICAL,
    }

    var_tt_to_try = {
        'some': BasicType.DEFERRED,
        'some%member': BasicType.DEFERRED
    }

    # Make sure none of the derived type members exist
    # in the symbol table initially
    for var_name in var_c_to_try:
        assert f'var_c%{var_name}' not in sub.symbol_attrs

    for var_name in var_tt_to_try:
        assert f'var_tt%{var_name}' not in sub.symbol_attrs

    assert 'var_c%c_b%b_a%a' == sub.resolve_typebound_var('var_c%c_b%b_a%a')

    # Create each derived type member and verify its type
    for var_name, dtype in var_c_to_try.items():
        var = var_c.get_derived_type_member(var_name)
        assert var == f'var_c%{var_name}'
        assert var.scope is sub
        assert isinstance(var, sym.Scalar)
        assert var.type.dtype == dtype

    for var_name, dtype in var_tt_to_try.items():
        var = var_tt.get_derived_type_member(var_name)
        assert var == f'var_tt%{var_name}'
        assert var.scope is sub
        assert isinstance(var, sym.DeferredTypeSymbol)
        assert var.type.dtype == dtype


# utility function to test parse_expr with different case
def convert_to_case(_str, mode='upper'):
    if mode == 'upper':
        return _str.upper()
    if mode == 'lower':
        return _str.lower()
    if mode == 'random':
        # this is obviously not random, but fulfils its purpose ...
        result = ''
        for i, char in enumerate(_str):
            result += char.upper() if i%2==0 and i<3 else char.lower()
        return result
    return convert_to_case(_str)


@pytest.mark.parametrize('case', ('upper', 'lower', 'random'))
@pytest.mark.parametrize('frontend', available_frontends())
def test_expression_parser(frontend, case):
    fcode = """
subroutine some_routine()
  implicit none
  integer :: i1, i2, i3, len1, len2, len3
  real :: a, b
  real :: arr(len1, len2, len3)
end subroutine some_routine
    """.strip()

    fcode_mod = """
module external_mod
  implicit none
contains
  function my_func(a)
    integer, intent(in) :: a
    integer :: my_func
    my_func = a
  end function my_func
end module external_mod
    """.strip()

    def to_str(_parsed):
        return str(_parsed).lower().replace(' ', '')

    routine = Subroutine.from_source(fcode, frontend=frontend)
    module = Module.from_source(fcode_mod, frontend=frontend)

    parsed = parse_expr(convert_to_case('a + b', mode=case))
    assert isinstance(parsed, sym.Sum)
    assert all(isinstance(_parsed,  sym.DeferredTypeSymbol) for _parsed in parsed.children)
    assert to_str(parsed) == 'a+b'

    parsed = parse_expr(convert_to_case('a + b', mode=case), scope=routine)
    assert isinstance(parsed, sym.Sum)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in parsed.children)
    assert all(_parsed.scope == routine for _parsed in parsed.children)
    assert to_str(parsed) == 'a+b'

    parsed = parse_expr(convert_to_case('a + b + 2 + 10', mode=case), scope=routine)
    assert isinstance(parsed, sym.Sum)
    assert to_str(parsed) == 'a+b+2+10'

    parsed = parse_expr(convert_to_case('a - b', mode=case), scope=routine)
    assert isinstance(parsed, sym.Sum)
    assert isinstance(parsed.children[0], sym.Scalar)
    assert isinstance(parsed.children[1], sym.Product)
    assert to_str(parsed) == 'a-b'

    parsed = parse_expr(convert_to_case('a * b', mode=case), scope=routine)
    assert isinstance(parsed, sym.Product)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in parsed.children)
    assert all(_parsed.scope == routine for _parsed in parsed.children)
    assert to_str(parsed) == 'a*b'

    parsed = parse_expr(convert_to_case('a / b', mode=case), scope=routine)
    assert isinstance(parsed, sym.Quotient)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.numerator, parsed.denominator])
    assert all(_parsed.scope == routine for _parsed in [parsed.numerator, parsed.denominator])
    assert to_str(parsed) == 'a/b'

    parsed = parse_expr(convert_to_case('a ** b', mode=case), scope=routine)
    assert isinstance(parsed, sym.Power)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.base, parsed.exponent])
    assert all(_parsed.scope == routine for _parsed in [parsed.base, parsed.exponent])
    assert to_str(parsed) == 'a**b'

    parsed = parse_expr(convert_to_case(':', mode=case))
    assert isinstance(parsed, sym.RangeIndex)
    assert to_str(parsed) == ':'

    parsed = parse_expr(convert_to_case('a:b', mode=case), scope=routine)
    assert isinstance(parsed, sym.RangeIndex)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.lower, parsed.upper])
    assert all(_parsed.scope == routine for _parsed in [parsed.lower, parsed.upper])
    assert to_str(parsed) == 'a:b'

    parsed = parse_expr(convert_to_case('a:b:5', mode=case), scope=routine)
    assert isinstance(parsed, sym.RangeIndex)
    assert all(isinstance(_parsed,  (sym.Scalar, sym.IntLiteral))
            for _parsed in [parsed.lower, parsed.upper, parsed.step])
    assert to_str(parsed) == 'a:b:5'

    parsed = parse_expr(convert_to_case('a == b', mode=case), scope=routine)
    assert parsed.operator == '=='
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a==b'
    parsed = parse_expr(convert_to_case('a.eq.b', mode=case), scope=routine)
    assert parsed.operator == '=='
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a==b'

    parsed = parse_expr(convert_to_case('a!=b', mode=case), scope=routine)
    assert parsed.operator == '!='
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a!=b'
    parsed = parse_expr(convert_to_case('a.ne.b', mode=case), scope=routine)
    assert parsed.operator == '!='
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a!=b'

    parsed = parse_expr(convert_to_case('a>b', mode=case), scope=routine)
    assert parsed.operator == '>'
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a>b'
    parsed = parse_expr(convert_to_case('a.gt.b', mode=case), scope=routine)
    assert parsed.operator == '>'
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a>b'

    parsed = parse_expr(convert_to_case('a>=b', mode=case), scope=routine)
    assert parsed.operator == '>='
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a>=b'
    parsed = parse_expr(convert_to_case('a.ge.b', mode=case), scope=routine)
    assert parsed.operator == '>='
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a>=b'

    parsed = parse_expr(convert_to_case('a<b', mode=case), scope=routine)
    assert parsed.operator == '<'
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a<b'
    parsed = parse_expr(convert_to_case('a.lt.b', mode=case), scope=routine)
    assert parsed.operator == '<'
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a<b'

    parsed = parse_expr(convert_to_case('a<=b', mode=case), scope=routine)
    assert parsed.operator == '<='
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a<=b'
    parsed = parse_expr(convert_to_case('a.le.b', mode=case), scope=routine)
    assert parsed.operator == '<='
    assert isinstance(parsed, sym.Comparison)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in [parsed.left, parsed.right])
    assert all(_parsed.scope == routine for _parsed in [parsed.left, parsed.right])
    assert to_str(parsed) == 'a<=b'

    parsed = parse_expr(convert_to_case('arr(i1, i2, i3)', mode=case))
    assert isinstance(parsed, sym.Array)
    assert all(isinstance(_parsed,  sym.DeferredTypeSymbol) for _parsed in parsed.dimensions)
    assert(parsed) == 'arr(i1,i2,i3)'
    parsed = parse_expr(convert_to_case('arr(i1, i2, i3)', mode=case), scope=routine)
    assert isinstance(parsed, sym.Array)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in parsed.dimensions)
    assert all(_parsed.scope == routine for _parsed in parsed.dimensions)
    if frontend == OMNI:
        assert all(isinstance(_parsed,  sym.RangeIndex) for _parsed in parsed.shape)
        assert all(isinstance(_parsed.upper,  sym.Scalar) for _parsed in parsed.shape)
        assert all(_parsed.upper.scope == routine for _parsed in parsed.shape)
    else:
        assert all(isinstance(_parsed,  sym.Scalar) for _parsed in parsed.shape)
        assert all(_parsed.scope == routine for _parsed in parsed.shape)
    assert to_str(parsed) == 'arr(i1,i2,i3)'

    parsed = parse_expr(convert_to_case('my_func(i1)', mode=case), scope=routine)
    assert isinstance(parsed, sym.Array)
    assert to_str(parsed) == 'my_func(i1)'
    parsed = parse_expr(convert_to_case('my_func(i1)', mode=case), scope=module)
    assert isinstance(parsed, sym.InlineCall)
    assert to_str(parsed) == 'my_func(i1)'

    parsed = parse_expr(convert_to_case('min(i1, i2)', mode=case), scope=module)
    assert isinstance(parsed, sym.InlineCall)
    assert to_str(parsed) == 'min(i1,i2)'

    parsed = parse_expr(convert_to_case('a', mode=case))
    assert isinstance(parsed, sym.DeferredTypeSymbol)
    assert to_str(parsed) == 'a'
    parsed = parse_expr(convert_to_case('a', mode=case), scope=routine)
    assert isinstance(parsed, sym.Scalar)
    assert parsed.scope == routine
    assert to_str(parsed) == 'a'
    parsed = parse_expr(convert_to_case('3.1415', mode=case))
    assert isinstance(parsed, sym.FloatLiteral)
    assert to_str(parsed) == '3.1415'

    parsed = parse_expr(convert_to_case('some_type%val', mode=case))
    assert isinstance(parsed, sym.DeferredTypeSymbol)
    assert isinstance(parsed.parent, sym.DeferredTypeSymbol)
    assert to_str(parsed) == 'some_type%val'
    parsed = parse_expr(convert_to_case('-some_type%val', mode=case))
    assert isinstance(parsed, sym.Product)
    assert isinstance(parsed.children[1].parent, sym.DeferredTypeSymbol)
    assert to_str(parsed) == '-some_type%val'
    parsed = parse_expr(convert_to_case('some_type%another_type%val', mode=case))
    assert isinstance(parsed, sym.DeferredTypeSymbol)
    assert isinstance(parsed.parent, sym.DeferredTypeSymbol)
    assert isinstance(parsed.parent.parent, sym.DeferredTypeSymbol)
    assert to_str(parsed) == 'some_type%another_type%val'
    parsed = parse_expr(convert_to_case('some_type%arr(a, b)', mode=case))
    assert isinstance(parsed, sym.Array)
    assert isinstance(parsed.parent, sym.DeferredTypeSymbol)
    assert to_str(parsed) == 'some_type%arr(a,b)'
    parsed = parse_expr(convert_to_case('some_type%some_func()', mode=case))
    assert isinstance(parsed, sym.InlineCall)
    assert isinstance(parsed.function.parent, sym.DeferredTypeSymbol)
    assert to_str(parsed) == 'some_type%some_func()'

    parsed = parse_expr(convert_to_case('"some_string_literal 42 _-*"', mode=case))
    assert isinstance(parsed, sym.StringLiteral)
    assert parsed.value.lower() == 'some_string_literal 42 _-*'
    assert to_str(parsed) == "'some_string_literal42_-*'"

    parsed = parse_expr(convert_to_case("'some_string_literal 42 _-*'", mode=case))
    assert isinstance(parsed, sym.StringLiteral)
    assert parsed.value.lower() == 'some_string_literal 42 _-*'
    assert to_str(parsed) == "'some_string_literal42_-*'"

    parsed = parse_expr(convert_to_case('MODULO(A, B)', mode=case), scope=routine)
    assert isinstance(parsed, sym.InlineCall)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in parsed.parameters)
    assert all(_parsed.scope == routine for _parsed in parsed.parameters)
    assert to_str(parsed) == 'modulo(a,b)'

    parsed = parse_expr(convert_to_case('a .and. b', mode=case))
    assert isinstance(parsed, sym.LogicalAnd)
    assert all(isinstance(_parsed,  sym.DeferredTypeSymbol) for _parsed in parsed.children)
    assert to_str(parsed) == 'aandb'
    parsed = parse_expr(convert_to_case('a .and. b', mode=case), scope=routine)
    assert isinstance(parsed, sym.LogicalAnd)
    assert all(isinstance(_parsed,  sym.Scalar) for _parsed in parsed.children)
    assert all(_parsed.scope == routine for _parsed in parsed.children)
    assert to_str(parsed) == 'aandb'
    parsed = parse_expr(convert_to_case('a .or. b', mode=case))
    assert isinstance(parsed, sym.LogicalOr)
    assert all(isinstance(_parsed,  sym.DeferredTypeSymbol) for _parsed in parsed.children)
    assert to_str(parsed) == 'aorb'
    parsed = parse_expr(convert_to_case('a .or. .not. b', mode=case))
    assert isinstance(parsed, sym.LogicalOr)
    assert isinstance(parsed.children[0], sym.DeferredTypeSymbol)
    assert isinstance(parsed.children[1], sym.LogicalNot)
    assert to_str('aornotb')

    parsed = parse_expr(convert_to_case('((a + b)/(a - b))**3 + 3.1415', mode=case), scope=routine)
    assert isinstance(parsed, sym.Sum)
    assert isinstance(parsed.children[0], sym.Power)
    assert isinstance(parsed.children[0].base, sym.Quotient)
    assert isinstance(parsed.children[0].base.numerator, sym.Sum)
    assert isinstance(parsed.children[0].base.denominator, sym.Sum)
    assert isinstance(parsed.children[1], sym.FloatLiteral)
    parsed_vars = FindVariables().visit(parsed)
    assert parsed_vars == ('a', 'b', 'a', 'b')
    assert all(parsed_var.scope == routine for parsed_var in parsed_vars)
    assert to_str(parsed) == '((a+b)/(a-b))**3+3.1415'

    parsed = parse_expr(convert_to_case('call_with_kwargs(a, val=7, end=b)', mode=case))
    assert isinstance(parsed, sym.InlineCall)
    assert parsed.parameters == ('a',)
    assert parsed.kw_parameters == {'val': 7, 'end': 'b'}
    assert to_str(parsed) == 'call_with_kwargs(a,val=7,end=b)'

    parsed = parse_expr(convert_to_case('real(6, kind=jprb)', mode=case))
    assert isinstance(parsed, sym.Cast)
    assert parsed.name.lower() == 'real'
    assert all(isinstance(_parsed, sym.IntLiteral) for _parsed in parsed.parameters)
    assert parsed.kind.name.lower() == 'jprb'
    assert to_str(parsed) == 'real(6)'

    parsed = parse_expr(convert_to_case('2.4', mode=case))
    assert isinstance(parsed, sym.FloatLiteral)
    assert parsed.kind is None
    assert to_str(parsed) == '2.4'

    parsed = parse_expr(convert_to_case('2.4_jprb', mode=case), scope=routine)
    assert isinstance(parsed, sym.FloatLiteral)
    assert parsed.kind == 'jprb'
    assert to_str(parsed) == '2.4_jprb'

    parsed = parse_expr(convert_to_case('2._8', mode=case), scope=routine)
    assert isinstance(parsed, sym.FloatLiteral)
    assert parsed.kind == '8'
    assert float(parsed.value) == 2.0
    assert to_str(parsed) == '2._8'

    parsed = parse_expr(convert_to_case('2.4e18_my_kind8', mode=case), scope=routine)
    assert isinstance(parsed, sym.FloatLiteral)
    assert parsed.kind == 'my_kind8'
    assert float(parsed.value) == 2.4e18
    assert to_str(parsed) == '2.4e18_my_kind8'

    parsed = parse_expr(convert_to_case('4_jpim', mode=case), scope=routine)
    assert isinstance(parsed, sym.IntLiteral)
    assert parsed.kind == 'jpim'
    assert int(parsed.value) == 4
    assert to_str(parsed) == '4'

    parsed = parse_expr(convert_to_case('[1, 2, 3, 4]', mode=case), scope=routine)
    assert isinstance(parsed, sym.LiteralList)
    assert all(isinstance(_parsed, sym.IntLiteral) for _parsed in parsed.elements)
    assert to_str(parsed) == '[1,2,3,4]'
    parsed = parse_expr(convert_to_case('(/ 2, 3, 4, 5 /)', mode=case), scope=routine)
    assert isinstance(parsed, sym.LiteralList)
    assert all(isinstance(_parsed, sym.IntLiteral) for _parsed in parsed.elements)
    assert to_str(parsed) == '[2,3,4,5]'

    parsed = parse_expr(convert_to_case('.TRUE.', mode=case))
    assert isinstance(parsed, sym.LogicLiteral)
    assert parsed.value is True
    assert to_str(parsed) == 'true'

    parsed = parse_expr(convert_to_case('.FALSE.', mode=case))
    assert isinstance(parsed, sym.LogicLiteral)
    assert parsed.value is False
    assert to_str(parsed) == 'false'

    parsed = parse_expr(convert_to_case('.FALSE. .OR. .TRUE. .AND. .TRUE.', mode=case))
    assert to_str(parsed) == 'falseortrueandtrue'


@pytest.mark.parametrize('case', ('upper', 'lower', 'random'))
def test_expression_parser_evaluate(case):

    test_str = '.FALSE. .OR. .TRUE. .AND. .TRUE.'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True)
    assert parsed

    context = {'a': 0.9}
    test_str = 'a .lt. 1'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed

    context = {'a': 0.9}
    test_str = 'a .lt. 1_jprb'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed

    context = {'VAR1': True, 'VAR2': False}
    test_str = 'VAR1 .AND. VAR2 .AND. .TRUE.'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed

    test_str = '(2*3)**2 - 16'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True)
    assert parsed == 20

    test_str = '(2*3)**2 - a'
    context = {'A': 6}
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 30

    test_str = '(2*3)**2 - a'
    context = {'a': 6}
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 30

    context = {'a': 6}
    test_str = 'min(a, 10)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 6
    test_str = '(2*3)**2 - min(a, 10)'
    context = {'a': 6}
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 30
    context = {'a': 6}
    test_str = 'max(a, 10)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 10

    context = {'a': 6, 'b': 2}
    test_str = 'modulo(A, B)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 0

    context = {'x': '4'}
    test_str = 'real(x)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 4.0
    assert isinstance(parsed, sym.FloatLiteral)

    context = {'a': '4.67'}
    test_str = 'int(a)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 4
    assert isinstance(parsed, sym.IntLiteral)

    context = {'x': '-4.145'}
    test_str = 'abs(x)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 4.145

    context = {'x': '9'}
    test_str = 'sqrt(x)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 3

    context = {'x': '0'}
    test_str = 'exp(x)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 1

    context = {'arr': [[1, 2], [3, 4]]}
    test_str = '1 + arr(1, 2)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 3

    context = {'a': 6}
    test_str = '1 + 1 + a + some_func(a, 10)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    with pytest.raises(pmbl_mapper.evaluator.UnknownVariableError):
        parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, strict=True, context=context)
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, strict=False, context=context)
    assert str(parsed).lower().replace(' ', '') == '8+some_func(6,10)'

    def some_func(a, b, c=None):
        if c is None:
            return a + b
        return a + b + c

    context = {'a': 6, 'some_func': some_func}
    test_str = '1 + 1 + a + some_func(a, 10)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 24

    context = {'a': 6, 'some_func': some_func}
    test_str = '1 + 1 + a + some_func(a, 10, c=2)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 26

    context = {'a': 6, 'b': 7}
    test_str = '(a + b + c + 1)/(c + 1)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert str(parsed).lower().replace(' ', '') == '(13+c+1)/(c+1)'

    class BarBarBar:
        val_barbarbar = 5

    class BarBar:
        barbarbar = BarBarBar()
        val_barbar = -3
        def barbar_func(self, a):
            return a - 1

    class Bar:
        barbar = BarBar()
        val_bar = 5
        def bar_func(self, a):
            return a**2

    class Foo:
        bar = Bar() # pylint: disable=disallowed-name
        val3 = 1
        arr = [[1, 2], [3, 4]]
        def __init__(self, _val1, _val2):
            self.val1 = _val1
            self.val2 = _val2
        def some_func(self, a, b):
            return a + b
        @staticmethod
        def static_func(a):
            return 2*a

    context = {'foo': Foo(2, 3)}
    test_str = 'foo%val1 + foo%val2 + foo%val3'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case))
    assert str(parsed).lower().replace(' ', '') == 'foo%val1+foo%val2+foo%val3'
    with pytest.raises(pmbl_mapper.evaluator.UnknownVariableError):
        parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, strict=True)
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 6
    test_str = 'foo%val1 + foo%some_func(1, 2) + foo%static_func_2(3)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert str(parsed).lower().replace(' ', '') == '5+foo%static_func_2(3)'
    with pytest.raises(pmbl_mapper.evaluator.UnknownVariableError):
        parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, strict=True)
    test_str = 'foo%val1 + foo%some_func(1, 2) + foo%static_func(3) + foo%arr(1, 2)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context, strict=True)
    assert parsed == 13
    test_str = 'foo%val1 + foo%some_func(1, b=2) + foo%static_func(a=3) + foo%arr(1, 2)'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context, strict=True)
    assert parsed == 13
    test_str = 'foo%bar%val_bar + 1'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 6
    test_str = 'foo%bar%bar_func(2) + 1'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 5
    test_str = 'foo%bar%barbar%val_barbar + 1'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == -2
    test_str = 'foo%bar%barbar%barbar_func(0) + 1'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 0
    test_str = 'foo%bar%barbar%barbarbar%val_barbarbar + 1'
    parsed = parse_expr(convert_to_case(f'{test_str}', mode=case), evaluate=True, context=context)
    assert parsed == 6
