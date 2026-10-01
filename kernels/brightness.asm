; One thread processes one grayscale pixel. Launch at most 128 threads.
; Memory: input [0, 127], output [128, 255]. All arithmetic is unsigned 8-bit.
; Host substitutions: k, half_k = floor(k/2), odd_k = k mod 2.
;
; Detect overflow without a wrapping sum or divergent branches:
; h = floor(p/2) + floor(k/2) + (p mod 2)*(k mod 2) = floor((p+k)/2).
; h <= 255, so carry = floor(h/128) is exactly 1 when p+k >= 256.
; wrapped = (p+k) mod 256; result = wrapped + carry*(255-wrapped).
; Thus p+k == 255 also correctly yields 255 with carry == 0.

MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
LDR R1, R0

CONST R2, #2
CONST R3, #128
CONST R4, #255
CONST R5, #{k}
CONST R6, #{half_k}
CONST R7, #{odd_k}

DIV R8, R1, R2          ; floor(p/2)
MUL R9, R8, R2          ; 2*floor(p/2) <= 254
SUB R9, R1, R9          ; p mod 2
MUL R9, R9, R7          ; carry from adding the low bits
ADD R8, R8, R6          ; sum of halves <= 254
ADD R8, R8, R9          ; floor((p+k)/2) <= 255
DIV R8, R8, R3          ; overflow carry: 0 or 1
ADD R10, R1, R5         ; wrapped 8-bit sum
SUB R11, R4, R10        ; distance from wrapped sum to 255
MUL R11, R8, R11        ; correction only if sum overflowed
ADD R12, R10, R11       ; saturated result

ADD R0, R0, R3          ; output address = 128 + thread index
STR R0, R12
RET
