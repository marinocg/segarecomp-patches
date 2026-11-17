; bounded retry of a section load whose object allocation failed (pool full). Experiment (gameplay-changing).
; state: 0xfffc00 .w col, +2 .w row, +4 .l list pointer of the loader call in progress; +8 .b fail flag; +9 .b retrying flag
;        ring of 4 slots at 0xfffc10, 12 bytes each: col.w row.w list.l attempts.w pad.w ; +0xc .l saved slot pointer
free usa-europe 0x00060c80 0x00000400 0xff
org usa-europe 0x00060c80
entry_hook:
  move.w d2,0xfffc00
  move.w d5,0xfffc02
  move.l a2,0xfffc04
  move.l a2,-(sp)
  move.l d7,-(sp)
  move.l d5,-(sp)
  move.l d2,-(sp)
  moveq #0,d3
  jmp @s_load_cont
org usa-europe 0x00060cc0
fail_hook:
  dbra d6,again
  tst.b 0xfffc09
  bne.s mark
  move.l d0,-(sp)
  move.l d1,-(sp)
  move.l a0,-(sp)
  lea 0xfffc10,a0
  moveq #3,d0
dup1:
  tst.w 8(a0)
  beq.s dup2
  move.w 0xfffc00,d1
  cmp.w (a0),d1
  bne.s dup2
  move.w 0xfffc02,d1
  cmp.w 2(a0),d1
  beq.s done
dup2:
  lea 12(a0),a0
  dbra d0,dup1
  lea 0xfffc10,a0
  moveq #3,d0
emp1:
  tst.w 8(a0)
  bne.s emp2
  move.w 0xfffc00,(a0)
  move.w 0xfffc02,2(a0)
  move.l 0xfffc04,4(a0)
  move.w #24,8(a0)
  bra.s done
emp2:
  lea 12(a0),a0
  dbra d0,emp1
done:
  movea.l (sp)+,a0
  move.l (sp)+,d1
  move.l (sp)+,d0
mark:
  move.b #1,0xfffc08
  jmp @s_next
again:
  jmp @s_loop
org usa-europe 0x00060e00
frame_hook:
  lea 0xfffa80,a6
  jsr @s_vert
  move.l d0,-(sp)
  move.l d1,-(sp)
  move.l d2,-(sp)
  move.l d3,-(sp)
  move.l d4,-(sp)
  move.l d5,-(sp)
  move.l d6,-(sp)
  move.l d7,-(sp)
  move.l a0,-(sp)
  move.l a1,-(sp)
  move.l a2,-(sp)
  move.l a3,-(sp)
  move.l a4,-(sp)
  move.l a5,-(sp)
  lea 0xfffc10,a0
  moveq #3,d0
r1:
  tst.w 8(a0)
  bne.s found
  lea 12(a0),a0
  dbra d0,r1
  bra.s out
found:
  subq.w #1,8(a0)
  move.l a0,0xfffc0c
  clr.b 0xfffc08
  move.b #1,0xfffc09
  move.w (a0),d2
  move.w 2(a0),d5
  movea.l 4(a0),a2
  lea 0xffffca02,a1
  jsr @s_load
  clr.b 0xfffc09
  tst.b 0xfffc08
  bne.s out
  movea.l 0xfffc0c,a0
  clr.w 8(a0)
out:
  movea.l (sp)+,a5
  movea.l (sp)+,a4
  movea.l (sp)+,a3
  movea.l (sp)+,a2
  movea.l (sp)+,a1
  movea.l (sp)+,a0
  move.l (sp)+,d7
  move.l (sp)+,d6
  move.l (sp)+,d5
  move.l (sp)+,d4
  move.l (sp)+,d3
  move.l (sp)+,d2
  move.l (sp)+,d1
  move.l (sp)+,d0
  jmp @s_ret
