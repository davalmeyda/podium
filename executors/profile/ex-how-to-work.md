## How to work

**Before changing a call to generated code, read its real signature.** Open the generated
file, find the method, and align argument by argument. Do not infer the signature from the
old call, and do not assume a parameter kept its position. When a signature gains a
parameter at the start, every positional call shifts one place and **still compiles** if
the types end up compatible — doing something completely different.

**Measure before deciding.** If the brief asks you to lower a limit, paginate something, or
change an aggregate, first find out the real size of the data. If truncating would break
something, **do not truncate silently: report it**. A truncated value without warning is
worse than leaving the problem in place.

**Do not invent workarounds.** If the brief asks you to do something the API does not
support, **stop and report it as blocked**. Do not disable the feature, do not comment it
out, do not leave it half-done: a disabled function is worse than a pending one, because it
looks finished.
