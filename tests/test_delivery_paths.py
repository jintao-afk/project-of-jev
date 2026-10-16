import tempfile
import unittest
from pathlib import Path

from core import ROOT
from delivery import deliver


class DeliveryRootTests(unittest.TestCase):
    def test_output_root_link_escape_is_rejected_before_any_file_is_written(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/tmp') as temporary:
            intended = Path(temporary)/'project'
            outside = Path(temporary)/'outside'
            class RedirectedRoot:
                def resolve(self):
                    return intended.resolve()
                def __truediv__(self, value):
                    return outside
            with self.assertRaisesRegex(ValueError, '项目以外'):
                deliver(RedirectedRoot(), {'run_id': 'a'*32}, {'goal': 'test'})
            self.assertFalse(outside.exists())


if __name__=='__main__':
    unittest.main()
