/*
 * Copyright 2018- The Pixie Authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

import * as React from 'react';

import { createStyles, makeStyles } from '@mui/styles';

import { UsernamePasswordButton } from 'app/components';

export interface HydraButtonsProps {
  usernamePasswordText: string;
  onUsernamePasswordButtonClick: () => void;
}

// eslint-disable-next-line react-memo/require-memo
export const HydraButtons: React.FC<HydraButtonsProps> = ({ usernamePasswordText, onUsernamePasswordButtonClick }) => (
  <>
    <UsernamePasswordButton
      text={usernamePasswordText}
      onClick={onUsernamePasswordButtonClick}
    />
  </>
);
HydraButtons.displayName = 'HydraButtons';

const useStyles = makeStyles(() => createStyles({
  rejectText: {
    color: 'red',
  },
}));

// eslint-disable-next-line react-memo/require-memo
export const RejectHydraSignup: React.FC = () => {
  const classes = useStyles();
  return (
    <div className={classes.rejectText}>
      Self-service sign up not supported for Open-Source authentication. Ask for an invite from your admin.
    </div>
  );
};
RejectHydraSignup.displayName = 'RejectHydraSignup';
