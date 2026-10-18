//=====================================================================
//
// KCP - A Better ARQ Protocol Implementation
// skywind3000 (at) gmail.com, 2011-2017
// Features:
//  + Average RTT reduce 30% - 40% vs TCP
//  + Maximum RTT reduce three times vs TCP
//  + Lightweight, distributed as a single source file
//
//=====================================================================
#ifndef __IKCP_H__
#define __IKCP_H__

#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#if defined(WIN32) || defined(_WIN32) || defined(WIN64) || defined(_WIN64)
#ifndef __psw_types__
#define __psw_types__
typedef unsigned int IUINT32;
typedef int IINT32;
typedef unsigned short IUINT16;
typedef short IINT16;
typedef unsigned char IUINT8;
typedef char IINT8;
#endif
#else
#include <stdint.h>
typedef uint32_t IUINT32;
typedef int32_t IINT32;
typedef uint16_t IUINT16;
typedef int16_t IINT16;
typedef uint8_t IUINT8;
typedef int8_t IINT8;
#endif

#ifdef __cplusplus
extern "C" {
#endif

//---------------------------------------------------------------------
// CONSTANTS
//---------------------------------------------------------------------
#define IKCP_RTO_NDL     30    // no delay min rto
#define IKCP_RTO_MIN     100   // normal min rto
#define IKCP_RTO_DEF     200
#define IKCP_RTO_MAX     60000
#define IKCP_CMD_PUSH    81    // cmd: push data
#define IKCP_CMD_ACK     82    // cmd: ack
#define IKCP_CMD_WASK    83    // cmd: window probe (ask)
#define IKCP_CMD_WINS    84    // cmd: window size (tell)
#define IKCP_ASK_SEND    1     // need to send IKCP_CMD_WASK
#define IKCP_ASK_TELL    2     // need to send IKCP_CMD_WINS
#define IKCP_WND_SND     32
#define IKCP_WND_RCV     128   // must >= max fragment size
#define IKCP_MTU_DEF     1400
#define IKCP_ACK_FAST    3
#define IKCP_INTERVAL    100
#define IKCP_OVERHEAD    24
#define IKCP_DEADLINK    20
#define IKCP_THRESH_INIT 2
#define IKCP_THRESH_MIN  2
#define IKCP_PROBE_INIT  7000   // 7 secs to probe window size
#define IKCP_PROBE_LIMIT 120000 // up to 120 secs to probe window

struct IKCPSEG;
struct IQUEUEHEAD {
    struct IQUEUEHEAD *next, *prev;
};
typedef struct IQUEUEHEAD iqueue_head;

typedef struct IKCPCB {
    IUINT32 conv, mtu, mss, state;
    IUINT32 snd_una, snd_nxt, rcv_nxt;
    IUINT32 ts_recent, ts_lastack, ssthresh;
    IINT32 rx_rttval, rx_srtt, rx_rto, rx_minrto;
    IUINT32 snd_wnd, rcv_wnd, rmt_wnd, cwnd, probe;
    IUINT32 current, interval, ts_flush, xmit;
    IUINT32 nrcv_buf, nsnd_buf;
    IUINT32 nrcv_que, nsnd_que;
    IUINT32 nodelay, updated;
    IUINT32 ts_probe, probe_wait;
    IUINT32 dead_link, incr;
    iqueue_head snd_queue;
    iqueue_head rcv_queue;
    iqueue_head snd_buf;
    iqueue_head rcv_buf;
    IUINT32 *acklist;
    IUINT32 ackcount;
    IUINT32 ackblock;
    void *user;
    char *buffer;
    int fastresend;
    int fastlimit;
    int nocwnd, stream;
    int logmask;
    int (*output)(const char *buf, int len, struct IKCPCB *kcp, void *user);
    void (*writelog)(const char *log, struct IKCPCB *kcp, void *user);
} ikcpcb;

ikcpcb* ikcp_create(IUINT32 conv, void *user);
void ikcp_release(ikcpcb *kcp);
void ikcp_setoutput(ikcpcb *kcp, int (*output)(const char *buf, int len, ikcpcb *kcp, void *user));
int ikcp_recv(ikcpcb *kcp, char *buffer, int len);
int ikcp_send(ikcpcb *kcp, const char *buffer, int len);
void ikcp_update(ikcpcb *kcp, IUINT32 current);
IUINT32 ikcp_check(const ikcpcb *kcp, IUINT32 current);
int ikcp_input(ikcpcb *kcp, const char *data, long size);
void ikcp_flush(ikcpcb *kcp);
int ikcp_peeksize(const ikcpcb *kcp);
int ikcp_setmtu(ikcpcb *kcp, int mtu);
int ikcp_wndsize(ikcpcb *kcp, int sndwnd, int rcvwnd);
int ikcp_waitsnd(const ikcpcb *kcp);
int ikcp_nodelay(ikcpcb *kcp, int nodelay, int interval, int resend, int nc);

#ifdef __cplusplus
}
#endif

#endif
