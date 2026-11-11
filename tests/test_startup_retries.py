import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
if not (Path(__file__).resolve().parents[1]/'app').exists():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bootstrap import startup_k
from runtime import InfrastructureError


class StartupRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_openapi_warmup_is_retried_without_disabling_validation(self):
        warming=SimpleNamespace(code=1,out='',err='error validating data: failed to download openapi: the server is currently unable to handle the request')
        success=SimpleNamespace(code=0,out='created',err='')
        runner=SimpleNamespace(k=AsyncMock(side_effect=[warming,warming,success]))
        with patch('bootstrap.asyncio.sleep',new=AsyncMock()):
            self.assertIs(await startup_k(runner,'apply','-f','-',stdin='synthetic manifest'),success)
        self.assertEqual(runner.k.await_count,3)
        for call in runner.k.call_args_list:
            self.assertEqual(call.args,('apply','-f','-'))
            self.assertEqual(call.kwargs['stdin'],'synthetic manifest')
            self.assertLessEqual(call.kwargs['timeout'],30)

    async def test_invalid_manifests_and_access_denials_are_not_retried(self):
        for error in ('error validating data: unknown field','Forbidden: access denied'):
            failure=SimpleNamespace(code=1,out='',err=error)
            runner=SimpleNamespace(k=AsyncMock(return_value=failure))
            self.assertIs(await startup_k(runner,'apply','-f','-'),failure)
            self.assertEqual(runner.k.await_count,1)

    async def test_deadline_bounds_the_request_itself(self):
        async def stalled(*args,**kwargs):
            await asyncio.Event().wait()
        runner=SimpleNamespace(k=stalled)
        with self.assertRaisesRegex(InfrastructureError,'timed out'):
            await startup_k(runner,'apply','-f','-',retry_timeout=.02)

    async def test_cancellation_propagates(self):
        runner=SimpleNamespace(k=AsyncMock(side_effect=asyncio.CancelledError))
        with self.assertRaises(asyncio.CancelledError):
            await startup_k(runner,'apply','-f','-')

    async def test_repeated_temporary_errors_exhaust_the_deadline(self):
        failure=SimpleNamespace(code=1,out='',err='ServiceUnavailable')
        runner=SimpleNamespace(k=AsyncMock(return_value=failure))
        self.assertIs(await startup_k(runner,'apply','-f','-',retry_timeout=.02),failure)


if __name__=='__main__': unittest.main()
