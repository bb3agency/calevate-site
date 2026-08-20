> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Make Outbound Calls Using Bolna Voice AI Agents

> Make outbound Voice AI calls with Bolna using default or dedicated phone numbers. Integrate telephony providers and automate calls via dashboard and APIs.

export const MakeComIcon = ({size = "24"}) => <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512">
  <defs>
    <radialGradient id="radial-gradient" cx="1.001" cy="0.064" r="1.618" gradientTransform="translate(0.147) scale(0.706 1)" gradientUnits="objectBoundingBox">
      <stop offset="0.2" stop-color="#f024f6" />
      <stop offset="0.386" stop-color="#c416f8" />
      <stop offset="0.61" stop-color="#9406f9" />
      <stop offset="0.722" stop-color="#8200fa" />
    </radialGradient>
    <clipPath id="clip-Make-IconColor-transparent">
      <rect width="512" height="512" />
    </clipPath>
  </defs>
  <g id="Make-IconColor-transparent" clip-path="url(#clip-Make-IconColor-transparent)">
    <g id="Logo_Dominos" data-name="Logo Dominos" transform="translate(90 150)">
      <path id="Path_203368" data-name="Path 203368" d="M1517.861,1588.687l43.727-185.587a6.7,6.7,0,0,1,8.083-5.038l52.083,12.71A6.832,6.832,0,0,1,1626.7,1419l-43.727,185.587a6.7,6.7,0,0,1-8.083,5.038l-52.083-12.71A6.854,6.854,0,0,1,1517.861,1588.687Zm122.055,19.758H1693.5a6.756,6.756,0,0,0,6.7-6.817V1410.772a6.756,6.756,0,0,0-6.7-6.818h-53.581a6.756,6.756,0,0,0-6.7,6.818v190.856A6.756,6.756,0,0,0,1639.917,1608.446Zm-232.191-27.176,48.155,23.917a6.632,6.632,0,0,0,8.946-3.143l82.233-171.514a6.859,6.859,0,0,0-3.088-9.1l-48.155-23.918a6.632,6.632,0,0,0-8.945,3.142l-82.21,171.491A6.877,6.877,0,0,0,1407.725,1581.27Z" transform="translate(-1403.973 -1396.819)" fill="url(#radial-gradient)" />
    </g>
  </g>
</svg>;

export const ZapierIcon = ({size = "24"}) => <svg viewBox="0 0 256 256" version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <g>
        <path d="M128.080089,-0.000183105 C135.311053,0.0131003068 142.422517,0.624138494 149.335663,1.77979593 L149.335663,1.77979593 L149.335663,76.2997796 L202.166953,23.6044907 C208.002065,27.7488446 213.460883,32.3582023 218.507811,37.3926715 C223.557281,42.4271407 228.192318,47.8867213 232.346817,53.7047992 L232.346817,53.7047992 L179.512985,106.400063 L254.227854,106.400063 C255.387249,113.29414 256,120.36111 256,127.587243 L256,127.587243 L256,127.759881 C256,134.986013 255.387249,142.066204 254.227854,148.960282 L254.227854,148.960282 L179.500273,148.960282 L232.346817,201.642324 C228.192318,207.460402 223.557281,212.919983 218.523066,217.954452 L218.523066,217.954452 L218.507811,217.954452 C213.460883,222.988921 208.002065,227.6115 202.182208,231.742607 L202.182208,231.742607 L149.335663,179.04709 L149.335663,253.5672 C142.435229,254.723036 135.323765,255.333244 128.092802,255.348499 L128.092802,255.348499 L127.907197,255.348499 C120.673691,255.333244 113.590195,254.723036 106.677048,253.5672 L106.677048,253.5672 L106.677048,179.04709 L53.8457596,231.742607 C42.1780766,223.466917 31.977435,213.278734 23.6658953,201.642324 L23.6658953,201.642324 L76.4997269,148.960282 L1.78485803,148.960282 C0.612750404,142.052729 0,134.946095 0,127.719963 L0,127.719963 L0,127.349037 C0.0121454869,125.473817 0.134939797,123.182933 0.311311815,120.812834 L0.36577283,120.099764 C0.887996182,113.428547 1.78485803,106.400063 1.78485803,106.400063 L1.78485803,106.400063 L76.4997269,106.400063 L23.6658953,53.7047992 C27.8076812,47.8867213 32.4300059,42.4403618 37.4769335,37.4193681 L37.4769335,37.4193681 L37.5023588,37.3926715 C42.5391163,32.3582023 48.0106469,27.7488446 53.8457596,23.6044907 L53.8457596,23.6044907 L106.677048,76.2997796 L106.677048,1.77979593 C113.590195,0.624138494 120.688946,0.0131003068 127.932622,-0.000183105 L127.932622,-0.000183105 L128.080089,-0.000183105 Z M128.067377,95.7600714 L127.945335,95.7600714 C118.436262,95.7600714 109.32891,97.5001809 100.910584,100.661566 C97.7553011,109.043534 96.0085811,118.129275 95.9958684,127.613685 L95.9958684,127.733184 C96.0085811,137.217594 97.7553011,146.303589 100.923296,154.685303 C109.32891,157.846943 118.436262,159.587052 127.945335,159.587052 L128.067377,159.587052 C137.576449,159.587052 146.683802,157.846943 155.089415,154.685303 C158.257411,146.290368 160.004131,137.217594 160.004131,127.733184 L160.004131,127.613685 C160.004131,118.129275 158.257411,109.043534 155.089415,100.661566 C146.683802,97.5001809 137.576449,95.7600714 128.067377,95.7600714 Z" fill="#FF4A00" fill-rule="nonzero">
</path>
    </g>
</svg>;

export const ExotelIcon = ({size = "24"}) => <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M2.49079 0.4688C3.81605 0.401981 4.98209 1.33934 5.20661 2.65142C5.4447 3.99963 6.09495 5.24013 7.06697 6.20122C8.70857 7.75742 11.2795 7.7461 12.9068 6.17486C13.0597 6.02893 13.2427 5.91825 13.4429 5.85161C13.8583 5.7215 14.3072 5.90473 14.5152 6.28814C14.7417 6.66861 14.6756 7.15607 14.3551 7.46099C13.8564 7.94086 13.5024 8.55196 13.3355 9.22466C12.9017 10.7798 13.4799 12.4417 14.7838 13.3887C15.6958 14.1014 16.7634 14.5865 17.899 14.8038C19.1625 15.0609 20.0524 16.2019 19.9976 17.4942C19.9427 18.7862 18.9597 19.8464 17.6793 19.9952C17.5399 20.0059 17.4271 19.9952 17.3199 19.9952C16.0674 20.0046 14.987 19.1152 14.7515 17.8809C14.52 16.6458 13.9648 15.4947 13.1431 14.5459C12.3388 13.6256 11.1776 13.0977 9.95759 13.0977C8.73757 13.0977 7.57638 13.6256 6.77204 14.5459C5.97137 15.4622 5.42957 16.5766 5.20173 17.7735C4.98983 18.9881 3.97264 19.8973 2.74568 19.9688C1.47381 20.0433 0.336258 19.1784 0.0640365 17.9297C-0.0933438 17.2149 0.0470102 16.4666 0.451732 15.8575C0.856482 15.2484 1.49132 14.8304 2.20954 14.7012C3.60678 14.4754 4.88388 13.7725 5.8238 12.711C6.50325 11.92 6.83716 10.8884 6.75154 9.84771C6.66585 8.80698 6.16742 7.84427 5.36775 7.17583C4.43203 6.40984 3.31701 5.89466 2.12849 5.67974C0.825448 5.42899 -0.085819 4.24109 0.00641932 2.91314C0.0987448 1.58515 1.16558 0.535634 2.49079 0.4688Z" fill="#212121" />
<path d="M17.273 5.04231e-05C17.9975 -0.00441912 18.6933 0.288415 19.2056 0.81255C19.7181 1.3369 20.004 2.04954 19.9996 2.79107C19.9995 4.33211 18.779 5.58095 17.273 5.58111C15.7669 5.58111 14.5456 4.33221 14.5455 2.79107C14.5455 1.24984 15.7668 5.04231e-05 17.273 5.04231e-05Z" fill="#212121" />
</svg>;

export const VobizIcon = ({size = "24"}) => <svg width="42" height="30" viewBox="0 0 42 30" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M42 14.7458V0C24.5641 0 12 13.7288 12 30H27.1282C27.1282 21.3559 33.5385 14.7458 42 14.7458Z" fill="#E83C00" />
        <path d="M0 15V0C9.28572 0 15 6.42857 15 15H0Z" fill="#E86A00" />
    </svg>;

export const PlivoIcon = ({size = "24"}) => <svg version="1.2" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 112 112">
      <defs>
        <clipPath clipPathUnits="userSpaceOnUse" id="cp1">
          <path d="m8 19h95.52v74.44h-95.52z" />
        </clipPath>
      <style>
        {`
          .s0 { opacity: 0; fill: #ffffff }
          .s1 { fill: #03A94A }
        `}
      </style>

      </defs>
      <g id="Layer">
        <path id="Layer" className="s0" d="m-23-13h362v138h-362z" />
        <g id="Layer">
          <g clipPath="url(#cp1)">
            <path id="Layer" fillRule="evenodd" className="s1" d="m77.3 26c6.1 4.5 10.7 10.8 13.1 18.1q0.2 0.4 0.4 0.8 0.3 0.4 0.7 0.6c3.8 2.4 6.9 5.8 9 9.7 2.1 3.9 3.2 8.5 3 13.3-0.3 7-3.4 13.2-8.2 17.7-4.8 4.5-11.3 7.2-18.3 7.2h-42.3c-7 0.1-13.5-2.6-18.3-7-4.8-4.4-8-10.6-8.4-17.6-0.2-4.8 0.9-9.3 3-13.3 2-4 5.1-7.3 8.8-9.7q0.4-0.3 0.7-0.7 0.3-0.3 0.5-0.8c2.3-7.3 6.9-13.6 13-18.1 6-4.5 13.5-7.2 21.6-7.2 8.1 0 15.6 2.6 21.7 7zm-37.9 7.8c-4.6 3.4-8.1 8.3-9.8 14.1l-0.4 1.2-0.3 1.2q-0.2 0.5-0.5 0.9-0.3 0.4-0.7 0.7l-2.3 1.3c-2.6 1.6-4.7 3.8-6.1 6.4-1.4 2.6-2.1 5.6-2 8.7 0.2 4.5 2.3 8.5 5.4 11.4 3.1 2.8 7.3 4.6 11.9 4.5h21.2l21.3-0.1c4.5 0 8.7-1.8 11.8-4.7 3.1-2.8 5.2-6.8 5.3-11.3 0.1-3.2-0.6-6.1-2-8.7-1.4-2.6-3.5-4.8-6.2-6.4l-1.1-0.6-1.1-0.7q-0.5-0.3-0.8-0.7-0.3-0.4-0.5-0.8l-0.7-2.5c-1.7-5.7-5.3-10.6-9.9-14-4.6-3.5-10.3-5.4-16.3-5.4-6 0-11.6 2-16.2 5.5z" />
          </g>
        </g>
        <path id="Layer" fillRule="evenodd" className="s1" d="m48.4 50.8c0 0.6-0.2 1.1-0.6 1.4-0.3 0.4-0.8 0.6-1.4 0.6h-2-2c-0.5 0-1-0.2-1.4-0.5-0.3-0.4-0.6-0.9-0.6-1.4v-4c0-0.6 0.3-1.1 0.6-1.4 0.4-0.4 0.9-0.6 1.4-0.6h4c0.5 0 1 0.2 1.4 0.5 0.4 0.4 0.6 0.9 0.6 1.4zm11.3 0c0 0.6-0.2 1.1-0.6 1.4-0.4 0.4-0.9 0.6-1.4 0.6h-2-2c-0.5 0-1-0.2-1.4-0.5-0.4-0.4-0.6-0.9-0.6-1.4v-4c0-0.6 0.2-1.1 0.6-1.4 0.3-0.4 0.8-0.6 1.4-0.6h4c0.5 0 1 0.2 1.4 0.6 0.3 0.3 0.6 0.8 0.6 1.4v1.9zm11.3 0c0 0.6-0.3 1.1-0.6 1.4-0.4 0.4-0.9 0.6-1.4 0.6h-2-2c-0.6 0.1-1.1-0.2-1.4-0.5-0.4-0.4-0.6-0.9-0.6-1.4v-2-2c0-0.6 0.2-1.1 0.6-1.4 0.3-0.4 0.8-0.6 1.4-0.6h3.9c0.6 0 1.1 0.2 1.5 0.5 0.3 0.4 0.6 0.9 0.6 1.4q0 0 0 0v0.1 2zm-22.6 11.2c0 0.6-0.2 1.1-0.6 1.4-0.3 0.4-0.8 0.6-1.4 0.6h-4c-0.5 0-1-0.2-1.4-0.5-0.3-0.4-0.5-0.9-0.6-1.4v-4c0-0.6 0.3-1.1 0.6-1.4 0.4-0.4 0.9-0.6 1.4-0.6h2 2c0.5 0 1 0.2 1.4 0.5 0.4 0.4 0.6 0.9 0.6 1.4zm11.3 0c0 0.6-0.2 1.1-0.6 1.4-0.4 0.4-0.9 0.6-1.4 0.6h-4c-0.5 0-1-0.2-1.4-0.5-0.4-0.4-0.6-0.9-0.6-1.4v-4c0-0.6 0.2-1.1 0.6-1.4 0.3-0.4 0.8-0.6 1.4-0.6h2 2c0.5 0 1 0.2 1.4 0.6 0.3 0.3 0.6 0.8 0.6 1.4v2zm11.3 0c0 0.5-0.3 1-0.6 1.4-0.4 0.3-0.9 0.5-1.4 0.5h-2l-2 0.1c-0.6 0-1.1-0.3-1.4-0.6-0.4-0.4-0.6-0.9-0.6-1.4v-2-2c0-0.6 0.2-1.1 0.6-1.4 0.3-0.4 0.8-0.6 1.4-0.6h2 2c0.5 0 1 0.2 1.4 0.6 0.3 0.3 0.5 0.8 0.5 1.4zm-22.5 11.2c0 0.6-0.2 1.1-0.6 1.4-0.4 0.4-0.9 0.6-1.4 0.6h-2-2c-0.5 0-1-0.2-1.4-0.5-0.4-0.4-0.6-0.9-0.6-1.4v-4c0-0.6 0.2-1.1 0.6-1.4 0.3-0.4 0.8-0.6 1.4-0.6h2 2c0.5 0 1 0.2 1.4 0.6 0.3 0.3 0.6 0.8 0.6 1.4v1.9zm11.3 0c0 0.6-0.3 1.1-0.6 1.4-0.4 0.4-0.9 0.6-1.4 0.6h-2-2c-0.6 0.1-1.1-0.2-1.4-0.5-0.4-0.4-0.6-0.9-0.6-1.4v-4c0-0.6 0.2-1.1 0.6-1.4 0.3-0.4 0.8-0.6 1.4-0.6h3.9c0.6 0 1.1 0.2 1.5 0.6 0.3 0.3 0.5 0.8 0.5 1.4v2zm11.3 0c0 0.5-0.2 1-0.5 1.4-0.4 0.3-0.9 0.5-1.4 0.5h-2l-2 0.1c-0.6 0-1.1-0.3-1.4-0.6-0.4-0.4-0.6-0.9-0.6-1.4v-2-2c0-0.6 0.2-1.1 0.5-1.4 0.4-0.4 0.9-0.6 1.4-0.6h4c0.6 0 1.1 0.2 1.4 0.6 0.4 0.3 0.6 0.8 0.6 1.4v2zm84.5-34.9q2.3 1.3 4.1 3.2 1.9 1.8 3.2 4.2 1.4 2.4 2.1 5.2 0.6 2.8 0.6 6 0.1 3.2-0.6 6-0.7 2.8-2 5.2-1.3 2.4-3.2 4.3-1.8 1.8-4.1 3.1-2.3 1.4-4.8 2-2.5 0.7-5.4 0.7-3.5 0-6.4-1.1-2.8-1-5-3.2v8.3 8.2c0 0.8-0.3 1.4-0.7 1.9-0.5 0.5-1.2 0.8-1.9 0.8l-4.6 0.1h-4.5c-0.7 0-1.4-0.3-1.9-0.8-0.5-0.5-0.8-1.2-0.8-1.9v-25.8l-0.1-25.8c0-0.8 0.3-1.4 0.8-1.9 0.5-0.5 1.1-0.8 1.9-0.8h4.2l4.1-0.1c0.8 0 1.4 0.3 1.9 0.8 0.5 0.5 0.8 1.2 0.8 1.9v0.9 0.8q2-2.3 5-3.6 3-1.2 7.1-1.2 2.8 0 5.4 0.7 2.5 0.6 4.8 1.9zm-5.2 25.8q1.2-1.3 1.8-3.1 0.6-1.8 0.6-4.1 0-2.2-0.7-4-0.6-1.8-1.8-3.1-1.2-1.3-2.8-2-1.5-0.6-3.4-0.6-1.9 0-3.5 0.7-1.5 0.6-2.7 1.9-1.2 1.3-1.8 3.1-0.6 1.8-0.6 4.1 0 2.3 0.6 4.1 0.6 1.8 1.8 3.1 1.2 1.3 2.8 1.9 1.6 0.7 3.5 0.7 1.8-0.1 3.4-0.7 1.6-0.7 2.8-2zm24.5-42.2h4.5 4.5c0.8 0 1.4 0.3 1.9 0.8 0.5 0.5 0.8 1.1 0.8 1.9v25.4 25.5c0 0.7-0.3 1.4-0.8 1.9-0.5 0.5-1.1 0.8-1.9 0.8h-4.5-4.5c-0.7 0-1.4-0.3-1.9-0.8-0.5-0.5-0.8-1.2-0.8-1.9v-25.4-25.5c0-0.7 0.3-1.4 0.8-1.9 0.5-0.5 1.1-0.8 1.9-0.8zm85.2 18.8l-3.7 8.9-3.6 9-3.7 8.9-3.7 9q-0.1 0.4-0.4 0.7-0.2 0.3-0.6 0.5-0.3 0.2-0.7 0.4-0.3 0.1-0.8 0.1h-2.8-2.8-2.8-2.8q-0.5 0-0.8-0.1-0.4-0.1-0.7-0.4-0.4-0.2-0.6-0.5-0.3-0.3-0.4-0.7l-3.7-8.9-3.7-9-3.7-9-3.6-8.9q-0.3-0.7-0.2-1.3 0-0.7 0.4-1.2 0.4-0.6 0.9-0.9 0.6-0.3 1.3-0.3h2.3l2.2-0.1h2.2 2.3q0.4 0 0.8 0.1 0.4 0.2 0.7 0.4 0.3 0.2 0.6 0.5 0.2 0.3 0.4 0.7l2.3 5.9 2.3 5.8 2.3 5.8 2.3 5.9 2.4-5.8 2.4-5.9 2.4-5.8 2.4-5.9q0.2-0.3 0.4-0.7 0.3-0.3 0.6-0.5 0.3-0.2 0.7-0.3 0.4-0.2 0.8-0.2h2 1.9 4q0.7 0 1.3 0.4 0.6 0.3 0.9 0.8 0.4 0.6 0.5 1.2 0.1 0.7-0.2 1.4zm13 34.3q-2.7-1.3-4.7-3.2-2.1-1.9-3.6-4.3-1.5-2.5-2.3-5.2-0.8-2.8-0.8-5.8 0-3.1 0.8-5.8 0.7-2.7 2.2-5.1 1.5-2.5 3.5-4.4 2.1-1.9 4.7-3.2 2.7-1.4 5.6-2.1 3-0.6 6.4-0.7 3.3 0 6.3 0.7 3 0.7 5.7 2 2.6 1.3 4.7 3.2 2.1 1.9 3.5 4.3 1.5 2.4 2.3 5.1 0.7 2.7 0.7 5.8 0.1 3.1-0.7 5.8-0.7 2.8-2.2 5.2-1.4 2.5-3.5 4.4-2.1 1.9-4.7 3.2-2.7 1.4-5.7 2.1-3 0.7-6.3 0.7-3.3 0-6.3-0.7-2.9-0.6-5.6-2zm18.1-11.4q1.2-1.3 1.8-3.1 0.6-1.8 0.6-4.1 0-2.3-0.6-4.1-0.6-1.8-1.9-3.1-1.2-1.2-2.7-1.9-1.6-0.6-3.5-0.6-1.9 0-3.4 0.6-1.6 0.7-2.8 2-1.2 1.3-1.8 3.1-0.6 1.8-0.6 4 0 2.3 0.6 4.1 0.6 1.9 1.8 3.2 1.3 1.3 2.8 1.9 1.6 0.7 3.5 0.7 1.9-0.1 3.4-0.7 1.6-0.7 2.8-2zm-84.4-29.6h-8.8c-0.8 0-1.5-0.3-2-0.8-0.5-0.5-0.8-1.2-0.8-1.9v-6.7c0-0.7 0.3-1.4 0.8-1.9 0.5-0.5 1.2-0.8 2-0.8h8.8c0.8 0 1.5 0.3 2 0.8 0.5 0.5 0.8 1.2 0.8 1.9v6.7c0 0.7-0.3 1.4-0.8 1.9-0.5 0.5-1.2 0.8-2 0.8zm0 44.2h-8.8c-0.8 0-1.5-0.3-2-0.8-0.5-0.5-0.8-1.2-0.8-2v-35.7c0-0.7 0.3-1.4 0.8-1.9 0.5-0.5 1.2-0.8 2-0.8h8.8c0.8 0 1.5 0.3 2 0.8 0.5 0.5 0.8 1.2 0.8 1.9v35.7c0 0.8-0.3 1.5-0.8 2-0.5 0.5-1.2 0.8-2 0.8z" />
      </g>
    </svg>;

export const TwilioIcon = ({size = "24"}) => <svg viewBox="0 0 256 256" version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" preserveAspectRatio="xMidYMid">
    <g>
        <path d="M128,0 C198.656,0 256,57.344 256,128 C256,198.656 198.656,256 128,256 C57.344,256 0,198.656 0,128 C0,57.344 57.344,0 128,0 Z M128,33.792 C75.776,33.792 33.792,75.776 33.792,128 C33.792,180.224 75.776,222.208 128,222.208 C180.224,222.208 222.208,180.224 222.208,128 C222.208,75.776 180.224,33.792 128,33.792 Z M159.744,133.12 C174.448029,133.12 186.368,145.039971 186.368,159.744 C186.368,174.448029 174.448029,186.368 159.744,186.368 C145.039971,186.368 133.12,174.448029 133.12,159.744 C133.12,145.039971 145.039971,133.12 159.744,133.12 Z M96.256,133.12 C110.960029,133.12 122.88,145.039971 122.88,159.744 C122.88,174.448029 110.960029,186.368 96.256,186.368 C81.5519708,186.368 69.632,174.448029 69.632,159.744 C69.632,145.039971 81.5519708,133.12 96.256,133.12 Z M159.744,69.632 C174.448029,69.632 186.368,81.5519708 186.368,96.256 C186.368,110.960029 174.448029,122.88 159.744,122.88 C145.039971,122.88 133.12,110.960029 133.12,96.256 C133.12,81.5519708 145.039971,69.632 159.744,69.632 Z M96.256,69.632 C110.960029,69.632 122.88,81.5519708 122.88,96.256 C122.88,110.960029 110.960029,122.88 96.256,122.88 C81.5519708,122.88 69.632,110.960029 69.632,96.256 C69.632,81.5519708 81.5519708,69.632 96.256,69.632 Z" fill="#F12E45">
</path>
    </g>
</svg>;

## How to make outbound calls with Bolna?

Bolna Voice AI enables you to make outbound calls in three ways: using Bolna's default phone numbers, purchasing dedicated numbers from Bolna, or connecting your own telephony provider. Choose the option that best fits your use case and brand requirements.

## Can I use Bolna's default numbers for outgoing calls?

By default, you can make outbound calls using Bolna's centralized phone numbers.

| Callee country      | Phone number prefix                                        |
| ------------------- | ---------------------------------------------------------- |
| 🇺🇸 United States  | Callee will recieve the phone call from `+1` prefix phone  |
| 🇬🇧 United Kingdom | Callee will recieve the phone call from `+1` prefix phone  |
| 🇦🇺 Australia      | Callee will recieve the phone call from `+1` prefix phone  |
| 🇮🇳 India          | Callee will recieve the phone call from `+91` prefix phone |
| 🌍 Others           | Callee will recieve the phone call from `+1` prefix phone  |

## How to use your own dedicated phone number?

### Method 1. Purchase a phone number from the [Bolna Dashboard](https://platform.bolna.ai/phone-numbers).

Please refer to a [step by step tutorial for purchasing phone numbers on Bolna](/docs/guides/inbound/buying-phone-numbers).

<Frame caption="Purchasing phone numbers on Bolna">
  <video controls className="w-full aspect-video" src="https://mintcdn.com/bolna-54a2d4fe/CY7jgPn0nDwFgdnc/videos/buying-phone-numbers.mp4?fit=max&auto=format&n=CY7jgPn0nDwFgdnc&q=85&s=f65e21bbd72e2a30c1476d9c2693b64e" data-path="videos/buying-phone-numbers.mp4" />
</Frame>

<br />

### Method 2. Connect your Telephony account and use your own phone numbers.

<CardGroup cols={2}>
  <Card
    title="Connect your Twilio account"
    icon={
  <>
    <TwilioIcon size="24" />
  </>
}
    href="/twilio-connect-provider"
  >
    Use your own Twilio phone numbers with Bolna
  </Card>

  <Card
    title="Connect your Plivo account"
    icon="phone-arrow-up-right"
    icon={
  <>
    <PlivoIcon size="24" />
  </>
}
    href="/plivo-connect-provider"
  >
    Use your own Plivo phone numbers with Bolna
  </Card>

  <Card
    title="Connect your Vobiz account"
    icon={
  <>
    <VobizIcon size="24" />
  </>
}
    href="/vobiz-connect-provider"
  >
    Use your own Vobiz phone numbers with Bolna
  </Card>

  <Card
    title="Connect your Exotel account"
    icon="phone-arrow-up-right"
    icon={
  <>
    <ExotelIcon size="24" />
  </>
}
    href="/exotel-connect-provider"
  >
    Use your own Exotel phone numbers with Bolna
  </Card>
</CardGroup>

***

## How to make outbound calls from the dashboard?

<Steps>
  <Step title="Click &#x22;Speak to your agent&#x22; button">
    <Frame caption="Click 'Speak to your agent' button to open the outbound call dialog">
      <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/making_outgoing_calls_step_1.png?fit=max&auto=format&n=DqJpudnR0YtgOS49&q=85&s=c4bdae0f14b79f81af098c1fb291b074" alt="Bolna Voice AI agent interface highlighting the 'Speak to your agent' button for initiating outbound calls from the dashboard" width="1410" height="996" data-path="images/making_outgoing_calls_step_1.png" />
    </Frame>
  </Step>

  <Step title="Choose country and calling from phone number">
    <Frame caption="Choosing country for purchasing phone numbers">
      <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/making_outgoing_calls_step_2.png?fit=max&auto=format&n=DqJpudnR0YtgOS49&q=85&s=ec409ca7a083d5a68a11ea2c7d8c0fc1" alt="Country selection and phone number configuration in Bolna Voice AI platform for outbound call parameters and caller ID" width="1462" height="1118" data-path="images/making_outgoing_calls_step_2.png" />
    </Frame>
  </Step>
</Steps>

## How to make outbound calls using APIs?

Use [`/call` API](api-reference/calls/make) to place the call to the agent

<CodeGroup>
  ```curl default-centralized-phone-numbers theme={"system"}

  # No need to add `from_phone_number`

  curl --request POST \
    --url https://api.bolna.ai/call \
    --header 'Authorization: <authorization>' \
    --header 'Content-Type: application/json' \
    --data '{
    "agent_id": "123e4567-e89b-12d3-a456-426655440000",
    "recipient_phone_number": "+10123456789"
  }'
  ```

  ```curl dedicated-phone-numbers theme={"system"}

  # Add your purchased phone number or your own connected phone number in `from_phone_number` field

  curl --request POST \
    --url https://api.bolna.ai/call \
    --header 'Authorization: <authorization>' \
    --header 'Content-Type: application/json' \
    --data '{
    "agent_id": "123e4567-e89b-12d3-a456-426655440000",
    "recipient_phone_number": "+10123456789",
    "from_phone_number": "+1987654321"
  }'
  ```
</CodeGroup>

## How to make outbound calls using Zapier & Make.com?

<CardGroup cols={2}>
  <Card
    title="Create Outbound calls on Zapier"
    icon={
  <>
    <ZapierIcon size="24" />
  </>
}
    href="https://zapier.com/apps/bolna/integrations"
  >
    Connect Zapier to start making outbound calls using Bolna Voice AI agents
  </Card>

  <Card
    title="Create Outbound calls on Make.com"
    icon="phone-arrow-up-right"
    icon={
  <>
    <MakeComIcon size="24" />
  </>
}
    href="https://www.make.com/en/integrations/bolna"
  >
    Connect Make.com to start making outbound calls using Bolna Voice AI agents
  </Card>
</CardGroup>

## Next steps

Ready to start making outbound calls? [Set up your first agent](/docs/agent-setup/agent-tab) or explore related features:

* [Batch calling](/docs/guides/outbound/batch-calling) for high-volume campaigns
* [Supported telephony providers](/docs/supported-telephony-providers) for integration options
* [Context variables](/docs/guides/prompting/using-context) to personalize each call
* [Call pricing](/docs/pricing/call-pricing) to understand costs

For receiving calls instead, see how to [handle inbound calls](/docs/guides/inbound/receiving-incoming-calls).
