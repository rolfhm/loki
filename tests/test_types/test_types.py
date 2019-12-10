import pytest
from pathlib import Path

from loki import OFP, FP, SourceFile


@pytest.fixture(scope='module')
def refpath():
    return Path(__file__).parent / 'types.f90'


def test_data_type():
    """
    Tests the conversion of strings to `DataType`.
    """
    from loki.types import DataType
    from random import choice

    fortran_type_map = {'LOGICAL': DataType.LOGICAL, 'INTEGER': DataType.INTEGER,
                        'REAL': DataType.REAL, 'CHARACTER': DataType.CHARACTER,
                        'COMPLEX': DataType.COMPLEX}

    # Randomly change case of single letters (FORTRAN is not case-sensitive)
    test_map = {''.join(choice((str.upper, str.lower))(c) for c in s): t
                for s, t in fortran_type_map.items()}

    assert all([t == DataType.from_fortran_type(s) for s, t in test_map.items()])
    assert all([t == DataType.from_str(s) for s, t in test_map.items()])

    c99_type_map = {'bool': DataType.LOGICAL, '_Bool': DataType.LOGICAL,
                    'short': DataType.INTEGER, 'unsigned short': DataType.INTEGER,
                    'signed short': DataType.INTEGER, 'int': DataType.INTEGER,
                    'unsigned int': DataType.INTEGER, 'signed int': DataType.INTEGER,
                    'long': DataType.INTEGER, 'unsigned long': DataType.INTEGER,
                    'signed long': DataType.INTEGER, 'long long': DataType.INTEGER,
                    'unsigned long long': DataType.INTEGER, 'signed long long': DataType.INTEGER,
                    'float': DataType.REAL, 'double': DataType.REAL, 'long double': DataType.REAL,
                    'char': DataType.CHARACTER, 'float _Complex': DataType.COMPLEX,
                    'double _Complex': DataType.COMPLEX, 'long double _Complex': DataType.COMPLEX}

    assert all([t == DataType.from_c99_type(s) for s, t in c99_type_map.items()])
    assert all([t == DataType.from_str(s) for s, t in c99_type_map.items()])


def test_symbol_type():
    """
    Tests the attachment, lookup and deletion of arbitrary attributes from
    class:``SymbolType``
    """
    from loki.types import SymbolType, DataType

    _type = SymbolType('integer', a='a', b=True, c=None)
    assert _type.dtype == DataType.INTEGER
    assert _type.a == 'a'
    assert _type.b
    assert _type.c is None
    assert _type.foo is None

    _type.foo = 'bar'
    assert _type.foo == 'bar'

    delattr(_type, 'foo')
    assert _type.foo is None


@pytest.mark.parametrize('frontend', [OFP, FP])  # OMNI segfaults with pragmas in derived types
def test_pragmas(refpath, frontend):
    """
    !$loki dimension(3,3)
    real(kind=jprb), dimension(:,:), pointer :: matrix
    !$loki dimension(5,1,5)
    real(kind=jprb), dimension(:,:,:), pointer :: tensor
    """
    from loki import FCodeMapper
    fsymgen = FCodeMapper()

    source = SourceFile.from_file(refpath, frontend=frontend)
    pragma_type = source['types'].types['pragma_type']

    assert fsymgen(pragma_type.variables['matrix'].shape) == '(3, 3)'
    assert fsymgen(pragma_type.variables['tensor'].shape) == '(klon, klat, 2)'
