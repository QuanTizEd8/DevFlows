/* Minimal C extension: one module exposing one function returning 42.
 * Enough to force a platform (non-pure) wheel that cibuildwheel repairs into a
 * manylinux wheel. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
speedup_answer(PyObject *self, PyObject *args)
{
    (void)self;
    (void)args;
    return PyLong_FromLong(42);
}

static PyMethodDef speedup_methods[] = {
    {"answer", speedup_answer, METH_NOARGS, "Return 42."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef speedup_module = {
    PyModuleDef_HEAD_INIT, "_speedup", NULL, -1, speedup_methods,
};

PyMODINIT_FUNC
PyInit__speedup(void)
{
    return PyModule_Create(&speedup_module);
}
